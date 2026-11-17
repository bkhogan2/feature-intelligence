"""Billing endpoints: admin-only mutations and exact signed webhook exception."""

from typing import Annotated
import logging
from fastapi import HTTPException, Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from app_core.domain.models import StrictModel, WorkspaceRole
from app_core.stripe_gateway import StripeSettings, StripeGateway
from app_core.billing import BillingService

logger = logging.getLogger(__name__)


class CheckoutRequest(StrictModel):
    plan: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]


def register_billing_routes(app, store, PrincipalDep, entitlements, service=None):
    settings = StripeSettings.from_env()
    if settings and service is None:
        service = BillingService(settings, StripeGateway(settings))

    def enabled():
        if not settings or not service:
            raise HTTPException(503, "Stripe billing is not enabled")

    def admin(principal):
        enabled()
        if principal.role != WorkspaceRole.ADMIN:
            raise HTTPException(
                403, "Workspace administrator access is required for billing"
            )

    def execute(operation, *args):
        try:
            return operation(*args)
        except HTTPException:
            raise
        except Exception:
            # Do not expose provider payloads, customer details, DSNs, or credentials.
            logger.warning(
                "Billing operation failed; provider/database reconciliation may be needed"
            )
            raise HTTPException(
                503,
                "Billing is temporarily unavailable. Retry or contact your operator",
            ) from None

    @app.get("/api/v1/billing")
    def summary(p: PrincipalDep):
        result = store.billing_summary(p, entitlements.livemode)
        return {
            **result,
            "enabled": bool(settings),
            "mode": "live" if entitlements.livemode else "test",
            "entitlements": entitlements.snapshot(p),
        }

    @app.post("/api/v1/billing/checkout")
    def checkout(payload: CheckoutRequest, p: PrincipalDep):
        admin(p)
        return execute(service.checkout, p, payload.plan)

    @app.post("/api/v1/billing/portal")
    def portal(p: PrincipalDep):
        admin(p)
        return execute(service.portal, p)

    @app.post("/api/v1/billing/refresh")
    def refresh(p: PrincipalDep):
        admin(p)
        execute(service.reconcile, p)
        return summary(p)

    @app.post("/api/v1/billing/webhook")
    async def webhook(request: Request):
        enabled()
        try:
            event = service.gateway.verify_event(
                await request.body(), request.headers.get("Stripe-Signature", "")
            )
            if not isinstance(event.get("id"), str) or not isinstance(
                event.get("data", {}).get("object"), dict
            ):
                raise ValueError("Invalid event")
            if event.get("livemode") is not settings.livemode or event.get("account"):
                raise ValueError("Wrong mode/account")
        except Exception:
            raise HTTPException(400, "Invalid Stripe webhook") from None
        return await run_in_threadpool(execute, service.webhook, event)
