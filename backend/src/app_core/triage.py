"""Durable run records + bounded local background tasks; independent of browser streams."""

import asyncio
import contextlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import sys
import tempfile
from uuid import UUID
from typing import Literal

from fastapi import HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from app_core.agent_settings import AgentSettings
from app_core.domain.models import WorkspaceRole
from app_core.triage_models import (
    PROMPT_VERSION,
    OpportunityDecision,
    OpportunityDescription,
    TriageConfirmation,
    TriageBatchConfirmation,
    TriageOutput,
    validate_result,
    triage_json_schema,
)

POLICY = AgentSettings(
    model="claude-haiku-5-5",
    max_turns=6,
    max_budget_usd=0.05,
    max_output_tokens=1800,
    request_timeout_seconds=120,
    max_concurrent_runs=2,
)


class TriageService:
    def __init__(self, store, refresh):
        self.store = store
        self.refresh = refresh
        self.tasks = {}
        self.gate = asyncio.Lock()
        self.dispatcher = None
        self.policy = AgentSettings(
            **{**POLICY.__dict__, "model": os.getenv("TRIAGE_MODEL", POLICY.model)}
        )

    def configured(self):
        return (
            os.getenv("TRIAGE_ENABLED") == "true"
            and bool(os.getenv("ANTHROPIC_API_KEY"))
            and importlib.util.find_spec("claude_agent_sdk") is not None
        )

    async def close(self):
        if self.dispatcher:
            self.dispatcher.cancel()
            await asyncio.gather(self.dispatcher, return_exceptions=True)
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def start(self, p, request, feedback_id, approval_id=None):
        async with self.gate:
            state = await run_in_threadpool(self.store.triage_state, p, feedback_id)
            if state is None:
                raise HTTPException(404, "Feedback not found")
            if not approval_id and state["run"] and state["run"]["status"] == "running":
                return state["run"]
            if not self.configured():
                raise HTTPException(
                    503,
                    "AI triage is not configured. Set the server-side Anthropic key and enable triage.",
                )
            if len(self.tasks) >= self.policy.max_concurrent_runs:
                raise HTTPException(
                    429, "Analysis capacity is busy. Try again shortly."
                )
            try:
                row, created = await run_in_threadpool(
                    self.store.start_triage,
                    p,
                    feedback_id,
                    self.policy.model,
                    PROMPT_VERSION,
                    self.policy.request_timeout_seconds + 10,
                    self.policy.max_budget_usd,
                    approval_id,
                )
            except ValueError as error:
                raise HTTPException(429, str(error)) from None
            if row is None:
                raise HTTPException(404, "Feedback not found")
            if created:
                task = asyncio.create_task(self.run(p, request, row))
                self.tasks[str(row["id"])] = task
                task.add_done_callback(
                    lambda _task: self.tasks.pop(str(row["id"]), None)
                )
            return row

    async def current(self, request, p):
        if request is None or request == "approval":
            from app_core.auth.identity import Principal

            access = await run_in_threadpool(
                self.store.get_active_access, p.tenant_id, p.subject
            )
            if not access or access.role not in {
                WorkspaceRole.ADMIN,
                WorkspaceRole.EDITOR,
            }:
                raise HTTPException(403, "Automatic analysis access changed")
            current = Principal(access.user_id, access.workspace, access.role)
            settings = await run_in_threadpool(self.store.auto_triage_config, current)
            if (
                request is None
                and not settings[getattr(self, "automatic_setting", "enabled")]
            ):
                raise HTTPException(403, "Automatic triage paused")
        else:
            current = await run_in_threadpool(self.refresh, request)
        if (current.subject, current.tenant_id) != (
            p.subject,
            p.tenant_id,
        ) or current.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise HTTPException(403, "Analysis access changed")
        return current

    async def run(self, p, request, row):
        process = None
        failure_message = "Analysis could not complete. Check model access or retry; no opportunity was changed."
        reported_cost = None
        try:
            async with asyncio.timeout(self.policy.request_timeout_seconds):
                current = await self.current(request, p)
                original = await run_in_threadpool(
                    self.store.feedback, current, row["feedback_id"]
                )
                if not original:
                    raise ValueError("Feedback unavailable")
                candidates = await run_in_threadpool(
                    self.store.opportunities, current, "", 20
                )
                clarification = await run_in_threadpool(
                    self.store.triage_clarifications, current, row["feedback_id"]
                )
                seen_feedback = {str(original["id"]): original}
                seen_opportunities = {
                    str(item["id"]): item for item in candidates["items"]
                }
                # Bound initial context and make truncation explicit, never invent evidence.
                candidates = {
                    **candidates,
                    "items": [
                        {
                            **item,
                            "problem": item["problem"][:1500],
                            "problem_truncated": len(item["problem"]) > 1500,
                        }
                        for item in candidates["items"]
                    ],
                }
                with tempfile.TemporaryDirectory(prefix="feature-triage-") as directory:
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

                    async def send(value):
                        process.stdin.write(
                            (json.dumps(value, default=str) + "\n").encode()
                        )
                        await process.stdin.drain()

                    await send(
                        {
                            "task": "triage",
                            "schema": triage_json_schema(),
                            "context": {
                                "request": original,
                                "submitter_clarifications": clarification,
                                "opportunities": candidates,
                            },
                        }
                    )
                    calls = 0
                    while raw := await process.stdout.readline():
                        if len(raw) > 100000:
                            raise ValueError("Oversized worker event")
                        event = json.loads(raw)
                        current = await self.current(request, p)
                        if event.get("type") == "tool":
                            calls += 1
                            if calls > 8:
                                raise ValueError("Tool budget exceeded")
                            args = event.get("arguments", {})
                            name = event.get("name")
                            if not isinstance(args, dict):
                                raise ValueError("Invalid tool arguments")
                            if name in {"search_opportunities", "search_feedback"}:
                                query = args.get("query", "")
                                if (
                                    set(args) != {"query"}
                                    or not isinstance(query, str)
                                    or len(query) > 120
                                ):
                                    raise ValueError("Invalid search")
                                if name == "search_opportunities":
                                    result = await run_in_threadpool(
                                        self.store.opportunities, current, query, 20
                                    )
                                    seen_opportunities.update(
                                        {
                                            str(item["id"]): item
                                            for item in result["items"]
                                        }
                                    )
                                else:
                                    found = await run_in_threadpool(
                                        self.store.list_feedback, current, query, 10, 0
                                    )
                                    result = {
                                        "items": [
                                            {
                                                "id": item["id"],
                                                "title": item["title"],
                                                "description": item["description"][
                                                    :1500
                                                ],
                                                "description_truncated": len(
                                                    item["description"]
                                                )
                                                > 1500,
                                            }
                                            for item in found["items"]
                                        ],
                                        "has_more": found["has_more"],
                                    }
                                    for item in result["items"]:
                                        seen_feedback.setdefault(str(item["id"]), item)
                            elif name == "get_opportunity":
                                if set(args) != {"id"}:
                                    raise ValueError("Invalid lookup")
                                result = await run_in_threadpool(
                                    self.store.opportunity, current, UUID(args["id"])
                                )
                                if result:
                                    seen_opportunities[str(result["id"])] = result
                                else:
                                    result = {
                                        "error": "Opportunity not found in this workspace."
                                    }
                            else:
                                raise ValueError("Unknown tool")
                            await send(result)
                        elif event.get("type") == "done":
                            cost = event.get("cost_usd")
                            if (
                                isinstance(cost, (int, float))
                                and math.isfinite(cost)
                                and cost >= 0
                            ):
                                reported_cost = cost
                            failure_codes = {
                                "error_max_turns": "Analysis reached its turn limit before producing a result.",
                                "error_max_budget_usd": "Analysis reached its spending limit before producing a result.",
                                "error_max_structured_output_retries": "The model could not produce a valid structured result.",
                                "error_during_execution": "The model provider rejected or interrupted the analysis.",
                            }
                            if event.get("error") or not isinstance(
                                event.get("result"), dict
                            ):
                                failure_message = (
                                    failure_codes.get(
                                        event.get("failure_code"),
                                        "The model returned no completed structured result.",
                                    )
                                    + " No opportunity was changed."
                                )
                                raise ValueError(
                                    "Model did not complete structured output"
                                )
                            output = TriageOutput.model_validate(event["result"])
                            validated = validate_result(
                                output.decision.model_dump(mode="json"),
                                seen_feedback,
                                seen_opportunities,
                                row["feedback_id"],
                            )
                            if validated[
                                "outcome"
                            ] == "existing_opportunity" and not await run_in_threadpool(
                                self.store.opportunity,
                                current,
                                UUID(validated["opportunity_id"]),
                            ):
                                raise ValueError("Opportunity no longer available")
                            cost = event.get("cost_usd")
                            if cost is not None and (
                                not isinstance(cost, (int, float))
                                or not math.isfinite(cost)
                                or cost < 0
                            ):
                                raise ValueError("Invalid cost")
                            await run_in_threadpool(
                                self.store.finish_triage,
                                current,
                                row["id"],
                                validated,
                                None,
                                cost,
                            )
                            return
                        else:
                            if event.get("failure_code") in {
                                "CLIConnectionError",
                                "ProcessError",
                                "MessageParseError",
                                "CLIJSONDecodeError",
                                "TimeoutError",
                                "TypeError",
                                "ValueError",
                                "sdk_error",
                            }:
                                failure_message = (
                                    "Analysis worker failed ("
                                    + event["failure_code"]
                                    + "). No opportunity was changed."
                                )
                            raise ValueError("Worker failed")
                    raise ValueError("Worker stopped without a result")
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await run_in_threadpool(
                    self.store.finish_triage,
                    p,
                    row["id"],
                    None,
                    "Analysis interrupted by server shutdown. Retry when ready.",
                )
            raise
        except Exception:
            # Never expose SDK errors, credentials, prompts or raw provider responses.
            with contextlib.suppress(Exception):
                await run_in_threadpool(
                    self.store.finish_triage,
                    p,
                    row["id"],
                    None,
                    failure_message,
                    reported_cost,
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


def register_triage_routes(app, store, principal_dependency, refresh):
    service = TriageService(store, refresh)
    app.state.triage_service = service
    from app_core.auto_triage import register_auto_triage_routes

    register_auto_triage_routes(app, store, principal_dependency)

    def require_editor(p):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise HTTPException(
                403, "An admin or editor must analyze or confirm requests"
            )

    @app.get("/api/v1/triage/config")
    def config(p: principal_dependency):
        return {
            "enabled": service.configured(),
            "model": service.policy.model,
            "prompt_version": PROMPT_VERSION,
            "max_budget_usd": service.policy.max_budget_usd,
            "timeout_seconds": service.policy.request_timeout_seconds,
            "can_analyze": p.role in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR},
            "automatic": store.auto_triage_config(p),
        }

    @app.get("/api/v1/feedback/{feedback_id}/triage")
    def state(feedback_id: UUID, p: principal_dependency):
        result = store.triage_state(p, feedback_id)
        if result is None:
            raise HTTPException(404, "Feedback not found")
        return result

    @app.post("/api/v1/feedback/{feedback_id}/triage", status_code=202)
    async def start(feedback_id: UUID, request: Request, p: principal_dependency):
        require_editor(p)
        return await service.start(p, request, feedback_id)

    @app.post("/api/v1/feedback/triage/confirm-batch")
    def confirm_batch(payload: TriageBatchConfirmation, p: principal_dependency):
        require_editor(p)
        try:
            return store.confirm_triage_batch(p, payload)
        except LookupError as error:
            raise HTTPException(404, str(error)) from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.post("/api/v1/feedback/{feedback_id}/triage/{run_id}/confirm")
    def confirm(
        feedback_id: UUID,
        run_id: UUID,
        p: principal_dependency,
        payload: TriageConfirmation | None = None,
    ):
        require_editor(p)
        try:
            result = store.confirm_triage(p, feedback_id, run_id, payload)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        if result is None:
            raise HTTPException(404, "Analysis not found")
        return result

    @app.get("/api/v1/opportunities")
    def opportunities(
        p: principal_dependency,
        search: str = "",
        include_archived: bool = False,
        limit: int = Query(default=30, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100_000),
        status: Literal[
            "all", "considering", "planned", "in_progress", "shipped", "not_pursuing"
        ] = "all",
    ):
        return store.opportunities(
            p,
            search.strip()[:200],
            limit=limit,
            status=status,
            include_archived=include_archived,
            offset=offset,
        )

    @app.get("/api/v1/opportunities/{opportunity_id}")
    def opportunity(opportunity_id: UUID, p: principal_dependency):
        result = store.opportunity(p, opportunity_id)
        if result is None:
            raise HTTPException(404, "Opportunity not found")
        return result

    @app.put("/api/v1/opportunities/{opportunity_id}/description")
    def save_description(
        opportunity_id: UUID, payload: OpportunityDescription, p: principal_dependency
    ):
        require_editor(p)
        try:
            result = store.save_opportunity_description(p, opportunity_id, payload)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        if result is None:
            raise HTTPException(404, "Opportunity not found")
        return result

    @app.post("/api/v1/opportunities/{opportunity_id}/decisions")
    def decide(
        opportunity_id: UUID, payload: OpportunityDecision, p: principal_dependency
    ):
        require_editor(p)
        try:
            result = store.decide_opportunity(p, opportunity_id, payload)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        if result is None:
            raise HTTPException(404, "Opportunity not found")
        return result
