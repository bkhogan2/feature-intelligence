"""Bounded, authenticated evidence assistant transport. Tools stay separate from the harness."""

import asyncio
import contextlib
import json
import os
import signal
from pathlib import Path
import secrets
import sys
import tempfile
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from app_core.agent_tools import domain_tool
from app_core.agent_settings import AgentSettings
from app_core.domain.models import StrictModel


class AgentContext(StrictModel):
    kind: Literal["feedback", "opportunity"]
    id: UUID


class AgentRequest(StrictModel):
    context: AgentContext | None = None
    message: Annotated[str, Field(min_length=1, max_length=4000)]


class ActionResult(StrictModel):
    action_id: Annotated[str, Field(max_length=100)]
    ok: bool


def register_agent_routes(app, store, principal_dependency, refresh_principal):
    # Each process owns its active runs, never shared model sessions.
    runs = {}
    settings = AgentSettings.from_env()

    def configured():
        return os.getenv("AGENT_ENABLED") == "true" and bool(
            os.getenv("ANTHROPIC_API_KEY")
        )

    @app.get("/api/v1/assistant/config")
    def config(p: principal_dependency):
        return {**settings.public_config(), "enabled": configured()}

    @app.post("/api/v1/assistant/runs/{run_id}/actions")
    async def action_result(
        run_id: str, payload: ActionResult, p: principal_dependency
    ):
        run = runs.get(run_id)
        if not run or run["owner"] != (p.subject, p.tenant_id):
            raise HTTPException(404, "Run not found")
        future = run["actions"].pop(payload.action_id, None)
        if future is None or future.done():
            raise HTTPException(409, "Action no longer pending")
        future.set_result(payload.ok)
        return {"accepted": True}

    @app.post("/api/v1/assistant/runs")
    async def start(payload: AgentRequest, request: Request, p: principal_dependency):
        if len(payload.message) > settings.max_message_chars:
            raise HTTPException(
                422, f"Message exceeds the {settings.max_message_chars}-character limit"
            )
        if not configured():
            raise HTTPException(
                503,
                "The workspace assistant is not configured.",
            )
        context = None
        if payload.context:
            context = await run_in_threadpool(
                domain_tool,
                store,
                p,
                "get_" + payload.context.kind,
                {"id": str(payload.context.id)},
            )
            if context.get("error"):
                raise HTTPException(404, "Selected record not found in this workspace")
            context = {"kind": payload.context.kind, "record": context}
        owner = (p.subject, p.tenant_id)
        if len(runs) >= settings.max_concurrent_runs or any(
            run["owner"] == owner for run in runs.values()
        ):
            raise HTTPException(
                429, "An assistant request is already running; try again shortly."
            )
        run_id = secrets.token_urlsafe(24)
        run = {"owner": owner, "actions": {}}
        runs[run_id] = run

        async def stream():
            process = None

            def line(event):
                return json.dumps(event) + "\n"

            try:
                with tempfile.TemporaryDirectory(prefix="starter-agent-") as directory:
                    # Subprocess receives only the model credential, never application secrets.
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
                            **settings.worker_env(),
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
                    )
                    process.stdin.write(
                        line({"message": payload.message, "context": context}).encode()
                    )
                    await process.stdin.drain()
                    yield line({"type": "start", "run_id": run_id})
                    finished = False
                    async with asyncio.timeout(settings.request_timeout_seconds):
                        while raw := await process.stdout.readline():
                            event = json.loads(raw)
                            if event["type"] == "tool":
                                # Revalidate sessions and membership after model latency.
                                current = await run_in_threadpool(
                                    refresh_principal, request
                                )
                                if (current.subject, current.tenant_id) != owner:
                                    raise HTTPException(403, "Assistant access changed")
                                name = event["name"]
                                yield line(
                                    {
                                        "type": "status",
                                        "message": "Reading workspace evidence…",
                                    }
                                )
                                result = await run_in_threadpool(
                                    domain_tool,
                                    store,
                                    current,
                                    name,
                                    event.get("arguments", {}),
                                )
                                process.stdin.write(line(result).encode())
                                await process.stdin.drain()
                            else:
                                if event["type"] in {"done", "error"}:
                                    finished = True
                                yield line(event)
                                if finished:
                                    break
                        if not finished:
                            yield line(
                                {
                                    "type": "error",
                                    "message": "Agent stopped before completing the request.",
                                }
                            )
            except HTTPException:
                yield line(
                    {
                        "type": "error",
                        "message": "Your access changed. Sign in and try again.",
                    }
                )
            except TimeoutError:
                yield line(
                    {
                        "type": "error",
                        "message": "The request timed out. No records were changed.",
                    }
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                yield line(
                    {
                        "type": "error",
                        "message": "The assistant could not complete this request.",
                    }
                )
            finally:
                runs.pop(run_id, None)
                for future in run["actions"].values():
                    future.cancel()
                if process and process.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGTERM)
                    try:
                        await asyncio.wait_for(process.wait(), timeout=3)
                    except TimeoutError:
                        with contextlib.suppress(ProcessLookupError):
                            os.killpg(process.pid, signal.SIGKILL)
                        await process.wait()

        return StreamingResponse(
            stream(),
            media_type="application/x-ndjson",
            headers={"X-Accel-Buffering": "no"},
        )
