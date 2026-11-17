"""Bounded, isolated Claude assessment; model output cannot confirm priority."""

import asyncio
import contextlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import tempfile
from uuid import UUID
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from app_core.domain.models import WorkspaceRole
from app_core.priority_models import (
    PriorityDecision,
    PrioritySuggestion,
    validate_suggestion,
)
from app_core.triage import TriageService


class PriorityService(TriageService):
    automatic_setting = "priority_enabled"

    async def start(self, p, request, oid):
        async with self.gate:
            if not self.configured():
                raise HTTPException(
                    503,
                    "AI assessment is not configured. You can still set priority manually.",
                )
            if len(self.tasks) >= self.policy.max_concurrent_runs:
                raise HTTPException(
                    429, "Analysis capacity is busy. Try again shortly."
                )
            try:
                row, created = await run_in_threadpool(
                    self.store.start_priority,
                    p,
                    oid,
                    self.policy.model,
                    self.policy.request_timeout_seconds + 10,
                    self.policy.max_budget_usd,
                )
            except ValueError as error:
                raise HTTPException(429, str(error)) from None
            if row is None:
                raise HTTPException(404, "Opportunity not found")
            if created:
                task = asyncio.create_task(self.run_priority(p, request, oid, row))
                self.tasks[row["id"]] = task
                task.add_done_callback(lambda _: self.tasks.pop(row["id"], None))
            return row

    async def run_priority(self, p, request, oid, row):
        process = None
        try:
            async with asyncio.timeout(self.policy.request_timeout_seconds):
                current = await self.current(request, p)
                detail = await run_in_threadpool(self.store.opportunity, current, oid)
                if not detail:
                    raise ValueError("Unavailable")
                feedback = [
                    {
                        key: item[key]
                        for key in ("id", "title", "description", "support_count")
                    }
                    for item in detail["feedback"][:20]
                ]
                for item in feedback:
                    item["description_truncated"] = len(item["description"]) > 3000
                    item["description"] = item["description"][:3000]
                context = {
                    key: detail[key]
                    for key in ("name", "problem", "status", "effort", "dependencies")
                }
                alternatives = await run_in_threadpool(
                    self.store.opportunities, current, "", 20
                )
                alternative_items = [
                    {
                        "id": str(item["id"]),
                        "name": item["name"],
                        "problem": item["problem"][:1500],
                        "problem_truncated": len(item["problem"]) > 1500,
                        "status": item["status"],
                        "confirmed_priority": item["priority"],
                        "linked_request_count": item["feedback_count"],
                    }
                    for item in alternatives["items"]
                    if str(item["id"]) != str(oid)
                ]
                context.update(
                    product_context=row["product_context"],
                    alternatives={
                        "items": alternative_items,
                        "has_more": alternatives["has_more"],
                        "scope": "Bounded workspace opportunity summaries; no independent outcome evidence",
                    },
                    feedback=feedback,
                    linked_feedback_count=len(detail["feedback"]),
                    evidence_truncated=len(detail["feedback"]) > 20,
                )
                row = {
                    **row,
                    "based_on_revision": detail["priority_revision"],
                    "evidence_count": len(detail["feedback"]),
                    "alternative_count": len(alternative_items),
                    "alternatives_truncated": alternatives["has_more"],
                }
                with tempfile.TemporaryDirectory(
                    prefix="feature-priority-"
                ) as directory:
                    env = {
                        key: os.environ[key]
                        for key in ("PATH", "LANG", "TMPDIR")
                        if key in os.environ
                    }
                    env.update(
                        {
                            "HOME": directory,
                            "CLAUDE_CONFIG_DIR": directory,
                            "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
                            **self.policy.worker_env(),
                            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                            "DISABLE_TELEMETRY": "1",
                            "DISABLE_ERROR_REPORTING": "1",
                        }
                    )
                    process = await asyncio.create_subprocess_exec(
                        sys.executable,
                        str(Path(__file__).with_name("agent_worker.py")),
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                        cwd=directory,
                        env=env,
                        start_new_session=True,
                        limit=131072,
                    )
                    process.stdin.write(
                        (
                            json.dumps(
                                {
                                    "task": "priority",
                                    "schema": PrioritySuggestion.model_json_schema(),
                                    "context": context,
                                },
                                default=str,
                            )
                            + "\n"
                        ).encode()
                    )
                    await process.stdin.drain()
                    while raw := await process.stdout.readline():
                        if len(raw) > 100000:
                            raise ValueError("Oversized event")
                        event = json.loads(raw)
                        if event.get("type") != "done" or event.get("error"):
                            raise ValueError("Worker failed")
                        result = validate_suggestion(event.get("result"), feedback)
                        cost = event.get("cost_usd")
                        if cost is not None and (
                            isinstance(cost, bool)
                            or not isinstance(cost, (int, float))
                            or not math.isfinite(cost)
                            or cost < 0
                        ):
                            raise ValueError("Invalid cost")
                        row = {**row, "cost_usd": cost}
                        current = await self.current(request, p)
                        await run_in_threadpool(
                            self.store.finish_priority, current, oid, row, result
                        )
                        return
                    raise ValueError("Worker stopped")
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await run_in_threadpool(
                    self.store.finish_priority,
                    p,
                    oid,
                    row,
                    None,
                    "Assessment interrupted. Retry when ready.",
                )
            raise
        except Exception:
            with contextlib.suppress(Exception):
                await run_in_threadpool(
                    self.store.finish_priority,
                    p,
                    oid,
                    row,
                    None,
                    "Assessment could not complete. Retry or set priority manually; confirmed priority was unchanged.",
                )
        finally:
            if process and process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()


def register_priority_routes(app, store, principal_dependency, refresh):
    service = PriorityService(store, refresh)
    app.state.priority_service = service
    from app_core.batch_priority import register_batch_priority_routes

    register_batch_priority_routes(app, store, principal_dependency, refresh, service)

    def require_editor(p):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise HTTPException(
                403, "An admin or editor must assess or confirm priority"
            )

    @app.post("/api/v1/opportunities/{oid}/priority/assess", status_code=202)
    async def assess(oid: UUID, request: Request, p: principal_dependency):
        require_editor(p)
        return await service.start(p, request, oid)

    @app.put("/api/v1/opportunities/{oid}/priority")
    def save(oid: UUID, payload: PriorityDecision, p: principal_dependency):
        require_editor(p)
        try:
            result = store.save_priority(p, oid, payload)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        if result is None:
            raise HTTPException(404, "Opportunity not found")
        return result
