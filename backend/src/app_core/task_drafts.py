"""Generate reviewable task drafts using the configured, isolated AI worker."""

import asyncio
import contextlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from typing import Annotated
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from app_core.domain.models import StrictModel
from app_core.tasks import Title, task_title_key


class TaskDraft(StrictModel):
    title: Title
    description: Annotated[
        str, Field(min_length=1, max_length=2400, pattern=r"^[^\x00]*$")
    ]


class DraftResult(StrictModel):
    drafts: Annotated[list[TaskDraft], Field(max_length=8)]
    questions: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=400)]], Field(max_length=4)
    ]


async def draft_subissues(context, policy):
    return await structured_draft("task_draft", DraftResult, context, policy)


async def structured_draft(mode, model, context, policy):
    with tempfile.TemporaryDirectory(prefix="feature-ai-draft-") as directory:
        env = {
            key: os.environ[key]
            for key in ("PATH", "LANG", "TMPDIR")
            if key in os.environ
        }
        env.update(
            HOME=directory,
            CLAUDE_CONFIG_DIR=directory,
            ANTHROPIC_API_KEY=os.environ["ANTHROPIC_API_KEY"],
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
            DISABLE_TELEMETRY="1",
            DISABLE_ERROR_REPORTING="1",
            **policy.worker_env(),
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
            limit=100_000,
        )
        try:
            message = {
                "task": mode,
                "schema": model.model_json_schema(),
                "context": context,
            }
            process.stdin.write((json.dumps(message) + "\n").encode())
            await process.stdin.drain()
            event = json.loads(await process.stdout.readline())
            if event.get("type") != "done" or event.get("error"):
                raise ValueError("AI worker failed")
            return model.model_validate(event["result"])
        finally:
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()


def register_task_draft_routes(app, store, principal_dependency, triage):
    slots = asyncio.Semaphore(2)

    @app.post("/api/v1/opportunities/{opportunity_id}/tasks/draft")
    async def draft(opportunity_id: UUID, request: Request, p: principal_dependency):
        store._require_task_editor(p)
        detail = await run_in_threadpool(store.opportunity, p, opportunity_id)
        if detail is None:
            raise HTTPException(404, "Opportunity not found")
        if detail["archived"]:
            raise HTTPException(
                409, "Restore the opportunity before drafting sub-issues."
            )
        if not triage.configured():
            raise HTTPException(503, "AI drafting is not configured.")
        existing = await run_in_threadpool(store.list_tasks, p, opportunity_id, 100, 0)
        rationale = ((detail["analysis"] or {}).get("result") or {}).get(
            "rationale_markdown"
        )
        description = detail["description_markdown"] or "\n\n".join(
            text for text in (detail["problem"], rationale) if text
        )
        context = {
            "title": detail["name"],
            "description": description[:8000],
            "linked_requests": [
                {"title": row["title"], "description": row["description"][:1500]}
                for row in detail["feedback"][:10]
            ],
            "existing_tasks": [
                {
                    "title": row["title"],
                    "status": row["status"],
                    "description": row["description"][:300],
                }
                for row in existing["items"]
            ],
        }
        if slots.locked():
            raise HTTPException(429, "AI drafting is busy. Try again in a moment.")
        async with slots:
            try:
                async with asyncio.timeout(60):
                    result = await draft_subissues(context, triage.policy)
            except Exception:
                raise HTTPException(
                    502, "AI couldn’t draft sub-issues. Try again."
                ) from None
        await triage.current(request, p)
        seen = {task_title_key(row["title"]) for row in existing["items"]}
        drafts = []
        for item in result.drafts:
            key = task_title_key(item.title)
            if key not in seen:
                seen.add(key)
                drafts.append(item)
        return DraftResult(drafts=drafts, questions=result.questions)
