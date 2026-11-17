"""Small in-process durable queue dispatcher; PostgreSQL owns claims, not browser sessions."""

import asyncio
import contextlib
from typing import Annotated
from decimal import Decimal
from fastapi import HTTPException
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from app_core.auth.identity import Principal
from app_core.domain.models import StrictModel, WorkspaceRole


class AutomationSettings(StrictModel):
    enabled: bool
    priority_enabled: bool | None = None
    daily_budget_usd: Annotated[
        Decimal,
        Field(ge=Decimal("0.05"), le=Decimal("5"), max_digits=3, decimal_places=2),
    ]


async def dispatch_once(service, after=""):
    rows = await run_in_threadpool(service.store.auto_triage_workspaces, after)
    for row in rows:
        representative = await run_in_threadpool(
            service.store.get_active_access, row["id"], row["user_id"]
        )
        if not representative:
            continue
        p = Principal(
            representative.user_id, representative.workspace, representative.role
        )
        await dispatch_approval(service, p)
        queued = await run_in_threadpool(service.store.queued_triage, p)
        if not service.configured():
            continue
        for job in queued:
            if len(service.tasks) >= service.policy.max_concurrent_runs:
                break
            access = await run_in_threadpool(
                service.store.get_active_access, row["id"], job["requested_by"]
            )
            if not access or access.role not in {
                WorkspaceRole.ADMIN,
                WorkspaceRole.EDITOR,
            }:
                await run_in_threadpool(fail_queued, service.store, p, job["id"])
                continue
            actor = Principal(access.user_id, access.workspace, access.role)
            with contextlib.suppress(HTTPException):
                await service.start(actor, None, job["feedback_id"])
    return rows[-1]["id"] if len(rows) == 50 else ""


def fail_queued(store, p, run_id):
    with store.connection(p) as db:
        db.execute(
            "UPDATE triage_runs SET status='failed',error='Submitter no longer has analysis access. An editor may retry manually.',completed_at=now() WHERE id=%s AND status='queued'",
            (run_id,),
        )


async def dispatch_loop(service):
    cursor = ""
    while True:
        try:
            cursor = await dispatch_once(service, cursor)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Pending rows remain durable on transient database/provider/configuration failures.
            cursor = ""
        await asyncio.sleep(2)


def register_auto_triage_routes(app, store, principal_dependency):
    @app.get("/api/v1/triage/automation")
    def config(p: principal_dependency):
        return store.auto_triage_config(p)

    @app.put("/api/v1/triage/automation")
    def save(payload: AutomationSettings, p: principal_dependency):
        if p.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
            raise HTTPException(
                403, "An admin or editor must change automatic triage settings"
            )
        return store.save_auto_triage_config(p, payload)


async def dispatch_approval(service, representative):
    job = await run_in_threadpool(service.store.pending_approval, representative)
    if not job:
        return
    access = await run_in_threadpool(
        service.store.get_active_access, representative.tenant_id, job["requested_by"]
    )
    if not access or access.role not in {WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}:
        await run_in_threadpool(
            service.store.fail_approval,
            representative,
            job["id"],
            "Reviewer no longer has approval access.",
        )
        return
    p = Principal(access.user_id, access.workspace, access.role)
    try:
        if await run_in_threadpool(service.store.advance_approval, p, job):
            return
        if not service.configured():
            raise ValueError(
                "AI linking is not configured. Link an opportunity manually or configure AI, then retry approval."
            )
        if not job["run_id"]:
            await service.start(
                p, "approval", job["feedback_id"], approval_id=job["id"]
            )
    except ValueError as e:
        await run_in_threadpool(service.store.fail_approval, p, job["id"], str(e))
    except HTTPException as e:
        if e.status_code != 429:
            await run_in_threadpool(
                service.store.fail_approval, p, job["id"], str(e.detail)
            )
