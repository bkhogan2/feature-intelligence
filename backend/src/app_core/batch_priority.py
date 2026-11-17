"""Bounded, isolated Claude assessment; model output cannot confirm priority."""

from dataclasses import replace
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


from app_core.priority import PriorityService
from app_core.priority_models import (
    BatchPriorityRequest,
    BatchPriorityResult,
    BatchPriorityDecisions,
    validate_batch_suggestions,
)


class BatchPriorityService(PriorityService):
    def __init__(self, store, refresh):
        super().__init__(store, refresh)
        # One joint request, bounded independently of user-supplied selection size.
        self.policy = replace(
            self.policy,
            max_output_tokens=32768,
            request_timeout_seconds=180,
        )

    async def start_batch(self, p, request, ids):
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
                row = await run_in_threadpool(
                    self.store.start_batch_priority,
                    p,
                    ids,
                    self.policy.model,
                    self.policy.request_timeout_seconds + 10,
                    self.policy.max_budget_usd,
                )
            except ValueError as error:
                raise HTTPException(409, str(error)) from None
            if row is None:
                raise HTTPException(404, "Opportunity not found")
            task = asyncio.create_task(self.run_batch(p, request, row))
            self.tasks[row["id"]] = task
            task.add_done_callback(lambda _: self.tasks.pop(row["id"], None))
            return row

    def finish_batch(self, p, row, results=None, error=None):
        for index, item in enumerate(row["items"]):
            run = {
                **item["analysis"],
                "cost_usd": row.get("cost_usd") if index == 0 else 0,
            }
            self.store.finish_priority(
                p,
                item["opportunity_id"],
                run,
                results[item["opportunity_id"]] if results is not None else None,
                error,
            )

    async def run_batch(self, p, request, row):
        process = None
        try:
            async with asyncio.timeout(self.policy.request_timeout_seconds):
                current = await self.current(request, p)
                evidence = {}
                opportunities = []
                for item in row["items"]:
                    detail = await run_in_threadpool(
                        self.store.opportunity, current, item["opportunity_id"]
                    )
                    if (
                        not detail
                        or detail["priority_revision"] != item["expected_revision"]
                        or detail.get(
                            "evidence_revision", item["expected_evidence_revision"]
                        )
                        != item["expected_evidence_revision"]
                    ):
                        raise ValueError("Opportunity changed before assessment")
                    feedback = [
                        {
                            key: f[key]
                            for key in ("id", "title", "description", "support_count")
                        }
                        for f in detail["feedback"][:10]
                    ]
                    for f in feedback:
                        f["description_truncated"] = len(f["description"]) > 1500
                        f["description"] = f["description"][:1500]
                    evidence[item["opportunity_id"]] = feedback
                    opportunities.append(
                        {
                            **{
                                key: detail[key]
                                for key in (
                                    "name",
                                    "problem",
                                    "status",
                                    "effort",
                                    "dependencies",
                                )
                            },
                            "id": item["opportunity_id"],
                            "current_priority": item["current_priority"],
                            "feedback": feedback,
                            "linked_feedback_count": len(detail["feedback"]),
                            "evidence_truncated": len(detail["feedback"]) > 10,
                        }
                    )
                context = {
                    "product_context": row["items"][0]["analysis"]["product_context"],
                    "scope": "Compare exactly these selected opportunities jointly. Other workspace opportunities are outside this assessment.",
                    "opportunities": opportunities,
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
                        limit=524288,
                    )
                    process.stdin.write(
                        (
                            json.dumps(
                                {
                                    "task": "priority_batch",
                                    "schema": BatchPriorityResult.model_json_schema(),
                                    "context": context,
                                },
                                default=str,
                            )
                            + "\n"
                        ).encode()
                    )
                    await process.stdin.drain()
                    while raw := await process.stdout.readline():
                        if len(raw) > 400000:
                            raise ValueError("Oversized event")
                        event = json.loads(raw)
                        if event.get("type") != "done":
                            raise ValueError("Worker failed")
                        cost = event.get("cost_usd")
                        if cost is not None and (
                            isinstance(cost, bool)
                            or not isinstance(cost, (int, float))
                            or not math.isfinite(cost)
                            or cost < 0
                        ):
                            raise ValueError("Invalid cost")
                        row = {**row, "cost_usd": cost}
                        if event.get("error"):
                            raise ValueError("Worker failed")
                        result = validate_batch_suggestions(
                            event.get("result"), evidence
                        )
                        current = await self.current(request, p)
                        await run_in_threadpool(self.finish_batch, current, row, result)
                        return
                    raise ValueError("Worker stopped")
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await run_in_threadpool(
                    self.finish_batch,
                    p,
                    row,
                    None,
                    "Assessment interrupted. Retry when ready.",
                )
            raise
        except Exception:
            with contextlib.suppress(Exception):
                await run_in_threadpool(
                    self.finish_batch,
                    p,
                    row,
                    None,
                    "Assessment could not complete within the server limits or returned invalid evidence. Try a smaller selection or set priority manually; confirmed priorities were unchanged.",
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


def register_batch_priority_routes(
    app, store, principal_dependency, refresh, shared_service
):
    service = BatchPriorityService(store, refresh)
    # Share process capacity and shutdown lifecycle with existing manual priority work.
    service.tasks = shared_service.tasks
    service.gate = shared_service.gate

    def editor(p):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise HTTPException(
                403, "An admin or editor must assess or confirm priority"
            )

    @app.post("/api/v1/opportunities/priority/batch-assess", status_code=202)
    async def assess(
        payload: BatchPriorityRequest, request: Request, p: principal_dependency
    ):
        editor(p)
        return await service.start_batch(p, request, payload.opportunity_ids)

    @app.get("/api/v1/opportunities/priority/batches/{batch_id}")
    def get_batch(batch_id: UUID, p: principal_dependency):
        result = store.batch_priority(p, batch_id)
        if result is None:
            raise HTTPException(404, "Assessment not found")
        return result

    @app.put("/api/v1/opportunities/priority/batch")
    def confirm(payload: BatchPriorityDecisions, p: principal_dependency):
        editor(p)
        try:
            result = store.save_batch_priority(p, payload.items)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        if result is None:
            raise HTTPException(404, "Opportunity not found")
        return result
