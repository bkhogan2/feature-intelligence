"""Durable post-approval priority dispatcher; same bounded isolated priority service."""

import asyncio
import contextlib
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from app_core.auth.identity import Principal
from app_core.domain.models import WorkspaceRole


async def dispatch_priority_once(service, after=""):
    rows = await run_in_threadpool(service.store.auto_triage_workspaces, after)
    for workspace in rows:
        representative = await run_in_threadpool(
            service.store.get_active_access, workspace["id"], workspace["user_id"]
        )
        if not representative:
            continue
        p = Principal(
            representative.user_id, representative.workspace, representative.role
        )
        jobs = await run_in_threadpool(service.store.queued_priority, p)
        if not service.configured():
            continue
        for job in jobs:
            if len(service.tasks) >= service.policy.max_concurrent_runs:
                break
            access = await run_in_threadpool(
                service.store.get_active_access, workspace["id"], job["requested_by"]
            )
            if not access or access.role not in {
                WorkspaceRole.ADMIN,
                WorkspaceRole.EDITOR,
            }:
                await run_in_threadpool(
                    service.store.fail_queued_priority,
                    p,
                    job["opportunity_id"],
                    job["id"],
                )
                continue
            actor = Principal(access.user_id, access.workspace, access.role)
            with contextlib.suppress(HTTPException):
                await service.start(actor, None, job["opportunity_id"])
    return rows[-1]["id"] if len(rows) == 50 else ""


async def dispatch_priority_loop(service):
    cursor = ""
    while True:
        try:
            cursor = await dispatch_priority_once(service, cursor)
        except asyncio.CancelledError:
            raise
        except Exception:
            cursor = ""
        await asyncio.sleep(2)
