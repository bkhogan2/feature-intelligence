"""Subscription orchestration with separate least-privilege database credentials."""

from contextlib import contextmanager
from datetime import UTC, datetime
import time
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException
from app_core.stripe_gateway import validate_price

TERMINAL = {"canceled", "incomplete_expired"}
EVENTS = {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.subscription.paused",
    "customer.subscription.resumed",
    "customer.subscription.trial_will_end",
    "customer.subscription.pending_update_applied",
    "customer.subscription.pending_update_expired",
    "checkout.session.completed",
    "checkout.session.expired",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
    "invoice.paid",
    "invoice.payment_failed",
    "invoice.finalization_failed",
}


def object_id(value):
    return value.get("id") if isinstance(value, dict) else value


class BillingService:
    def __init__(self, settings, gateway):
        self.settings = settings
        self.gateway = gateway
        # Fail before serving traffic if credentials accidentally have broad privileges.
        with psycopg.connect(settings.database_url, row_factory=dict_row) as db:
            roles = db.execute(
                "SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb FROM pg_roles WHERE rolname IN (current_user,'app_billing_service')"
            ).fetchall()
            unsafe = db.execute("""SELECT pg_has_role(current_user,'app_runtime','MEMBER')
                OR pg_has_role(current_user,'app_plan_operator','MEMBER')
                OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='app_core' AND pg_get_userbyid(nspowner)=current_user) AS value""").fetchone()[
                "value"
            ]
            if unsafe or any(any(r.values()) for r in roles):
                raise RuntimeError(
                    "BILLING_DATABASE_URL must use a separate restricted billing-service login"
                )
            db.execute("SET LOCAL ROLE app_billing_service")

    @contextmanager
    def connection(self, workspace=None):
        # Session lock spans committed attempt records + Stripe calls; connection close releases it.
        with psycopg.connect(
            self.settings.database_url,
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=10,
        ) as db:
            db.execute("SET ROLE app_billing_service")
            db.execute("SET search_path=pg_catalog,app_core")
            db.execute("SET lock_timeout='15s'")
            if workspace:
                db.execute(
                    "SELECT pg_advisory_lock(hashtextextended(%s,83142003))",
                    (f"{self.settings.livemode}:{workspace}",),
                )
            yield db

    def authorize(self, db, principal):
        row = db.execute(
            """SELECT m.role FROM memberships m JOIN workspaces w ON w.id=m.workspace_id
            WHERE m.workspace_id=%s AND m.user_id=%s AND m.status='active' AND w.status='active'""",
            (principal.tenant_id, principal.subject),
        ).fetchone()
        if not row or row["role"] != "admin":
            raise HTTPException(
                403, "Workspace administrator access is required for billing"
            )

    def account(self, db, workspace):
        return db.execute(
            "SELECT * FROM billing_accounts WHERE workspace_id=%s AND livemode=%s",
            (workspace, self.settings.livemode),
        ).fetchone()

    def ensure_customer(self, db, workspace):
        db.execute(
            "INSERT INTO billing_accounts(workspace_id,livemode,customer_request_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            (workspace, self.settings.livemode, str(uuid4())),
        )
        account = self.account(db, workspace)
        if not account["customer_id"]:
            # A stale ambiguous customer request needs operator attention, not a new create key.
            if (datetime.now(UTC) - account["created_at"]).total_seconds() > 23 * 3600:
                raise HTTPException(
                    409,
                    "Customer setup needs operator reconciliation; no new charge was created",
                )
            customer = self.gateway.create_customer(account["customer_request_id"])
            if customer.get("livemode") is not self.settings.livemode:
                raise ValueError("Stripe customer mode mismatch")
            db.execute(
                "UPDATE billing_accounts SET customer_id=%s WHERE workspace_id=%s AND livemode=%s",
                (customer["id"], workspace, self.settings.livemode),
            )
            account = self.account(db, workspace)
        return account

    def sync(self, db, account):
        # Fetch latest state inside the workspace lock: event delivery order/timestamps are irrelevant.
        subscriptions = self.gateway.subscriptions(account["customer_id"])
        seen = []
        with db.transaction():
            for listed in subscriptions:
                subscription = self.gateway.subscription(listed["id"])
                if (
                    object_id(subscription.get("customer")) != account["customer_id"]
                    or subscription.get("livemode") is not self.settings.livemode
                ):
                    raise ValueError("Stripe subscription customer/mode mismatch")
                seen.append(subscription["id"])
                items = subscription.get("items", {}).get("data", [])
                supported = (
                    len(items) == 1
                    and not subscription.get("items", {}).get("has_more")
                    and items[0].get("quantity") == 1
                )
                item = items[0] if supported else {}
                end = item.get("current_period_end")
                if subscription.get("status") == "trialing":
                    end = min(end or 0, subscription.get("trial_end") or 0)
                if subscription.get("cancel_at"):
                    end = min(end or 0, subscription["cancel_at"])
                payment_confirmed = self.payment_confirmed(subscription, item, account)
                db.execute(
                    """INSERT INTO billing_subscriptions(subscription_id,workspace_id,livemode,price_id,status,period_end,cancel_at_period_end,collection_paused,payment_confirmed)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(subscription_id) DO UPDATE SET
                    price_id=excluded.price_id,status=excluded.status,period_end=excluded.period_end,
                    cancel_at_period_end=excluded.cancel_at_period_end,collection_paused=excluded.collection_paused,payment_confirmed=excluded.payment_confirmed,synced_at=now()
                    WHERE billing_subscriptions.workspace_id=excluded.workspace_id AND billing_subscriptions.livemode=excluded.livemode""",
                    (
                        subscription["id"],
                        account["workspace_id"],
                        self.settings.livemode,
                        object_id(item.get("price")),
                        subscription["status"],
                        datetime.fromtimestamp(end, UTC) if end else None,
                        bool(subscription.get("cancel_at_period_end")),
                        bool(subscription.get("pause_collection")),
                        payment_confirmed,
                    ),
                )
            # The provider list is authoritative; revoke missing objects conservatively.
            db.execute(
                "UPDATE billing_subscriptions SET status='canceled',synced_at=now() WHERE workspace_id=%s AND livemode=%s AND NOT (subscription_id=ANY(%s))",
                (account["workspace_id"], self.settings.livemode, seen),
            )
        return subscriptions

    def payment_confirmed(self, subscription, item, account):
        if not item or subscription.get("pending_update"):
            return False
        if subscription["status"] == "trialing":
            return True  # Explicit trial policy; access is separately bounded by trial_end.
        invoice = subscription.get("latest_invoice")
        if (
            subscription["status"] != "active"
            or not isinstance(invoice, dict)
            or invoice.get("status") != "paid"
            or invoice.get("livemode") is not self.settings.livemode
            or object_id(invoice.get("customer")) != account["customer_id"]
        ):
            return False
        # An old paid invoice for Pro must never authorize an uninvoiced Enterprise upgrade.
        # Match the paid line to the current item/price and entire current access period.
        for line in self.gateway.invoice_lines(invoice["id"]):
            details = (line.get("parent") or {}).get("subscription_item_details") or {}
            price = ((line.get("pricing") or {}).get("price_details") or {}).get(
                "price"
            )
            if (
                details.get("subscription_item") == item.get("id")
                and details.get("subscription") == subscription["id"]
                and object_id(price) == object_id(item.get("price"))
                and line.get("livemode") is self.settings.livemode
                and line.get("amount", -1) >= 0
                and (line.get("period") or {}).get("end", 0)
                >= item.get("current_period_end", float("inf"))
            ):
                return True
        return False

    def checkout(self, principal, plan_key):
        with self.connection(principal.tenant_id) as db:
            self.authorize(db, principal)
            if db.execute(
                "SELECT 1 FROM workspace_plans WHERE workspace_id=%s",
                (principal.tenant_id,),
            ).fetchone():
                raise HTTPException(
                    409,
                    "This workspace has an operator-managed plan; contact your operator before subscribing",
                )
            price = db.execute(
                """SELECT b.* FROM billing_prices b JOIN plans p ON p.key=b.plan_key
                WHERE b.plan_key=%s AND b.livemode=%s AND b.checkout_enabled AND p.active""",
                (plan_key, self.settings.livemode),
            ).fetchone()
            if not price:
                raise HTTPException(404, "This plan is not available for checkout")
            validate_price(
                self.gateway.price(price["price_id"]), self.settings.livemode
            )
            account = self.ensure_customer(db, principal.tenant_id)
            if any(s["status"] not in TERMINAL for s in self.sync(db, account)):
                raise HTTPException(
                    409,
                    "A subscription already exists. Use Manage billing to change it",
                )
            attempt = db.execute(
                "SELECT * FROM billing_checkout_attempts WHERE workspace_id=%s AND livemode=%s AND status IN ('pending','open')",
                (principal.tenant_id, self.settings.livemode),
            ).fetchone()
            if attempt:
                session = (
                    self.gateway.session(attempt["session_id"])
                    if attempt["session_id"]
                    else self.gateway.find_session(
                        account["customer_id"], attempt["id"]
                    )
                )
                if session:
                    self.save_session(db, attempt, account, session)
                    if session["status"] == "open":
                        if attempt["price_id"] != price["price_id"]:
                            raise HTTPException(
                                409,
                                "Another checkout is open. Resume that plan or wait for it to expire",
                            )
                        return {"url": session["url"]}
                    if session["status"] == "complete":
                        self.sync(db, account)
                        raise HTTPException(
                            409,
                            "Checkout completed. Refresh billing or open Manage billing",
                        )
                    attempt = None
                elif attempt["expires_at"] <= int(time.time()) + 1800:
                    # Do not recreate ambiguous sessions with an expired immutable expires_at.
                    raise HTTPException(
                        409,
                        "Checkout recovery needs operator reconciliation; no new checkout was created",
                    )
                elif attempt["price_id"] != price["price_id"]:
                    raise HTTPException(
                        409, "Another checkout is pending. Retry its original plan"
                    )
            if not attempt:
                attempt = db.execute(
                    """INSERT INTO billing_checkout_attempts(id,workspace_id,livemode,price_id,return_url,expires_at)
                    VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (
                        str(uuid4()),
                        principal.tenant_id,
                        self.settings.livemode,
                        price["price_id"],
                        self.settings.public_url,
                        int(time.time()) + 3600,
                    ),
                ).fetchone()
            session = self.gateway.checkout(attempt, account["customer_id"])
            self.save_session(db, attempt, account, session)
            return {"url": session["url"]}

    def save_session(self, db, attempt, account, session):
        if (
            object_id(session.get("customer")) != account["customer_id"]
            or session.get("livemode") is not self.settings.livemode
            or session.get("client_reference_id") != attempt["id"]
            or session.get("mode") != "subscription"
        ):
            raise ValueError("Checkout association mismatch")
        db.execute(
            "UPDATE billing_checkout_attempts SET session_id=%s,url=%s,status=%s WHERE id=%s",
            (session["id"], session.get("url"), session["status"], attempt["id"]),
        )

    def portal(self, principal):
        with self.connection(principal.tenant_id) as db:
            self.authorize(db, principal)
            account = self.account(db, principal.tenant_id)
            if not account or not account["customer_id"]:
                raise HTTPException(409, "No Stripe customer exists for this workspace")
            return {"url": self.gateway.portal(account["customer_id"])["url"]}

    def reconcile(self, principal):
        with self.connection(principal.tenant_id) as db:
            self.authorize(db, principal)
            account = self.account(db, principal.tenant_id)
            if account and account["customer_id"]:
                self.sync(db, account)
        return {"refreshed": True}

    def webhook(self, event):
        if event.get("livemode") is not self.settings.livemode or event.get("account"):
            raise ValueError("Wrong Stripe mode or connected-account event")
        if event["type"] not in EVENTS:
            return {"received": True}
        customer = object_id(event["data"]["object"].get("customer"))
        # Metadata is never used to establish a tenant/customer binding.
        with self.connection() as lookup:
            account = lookup.execute(
                "SELECT * FROM billing_accounts WHERE customer_id=%s AND livemode=%s",
                (customer, self.settings.livemode),
            ).fetchone()
        if not account:
            return {"received": True}
        with self.connection(account["workspace_id"]) as db:
            with db.transaction():
                claimed = db.execute(
                    "INSERT INTO billing_events(event_id,livemode,event_type) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING event_id",
                    (event["id"], self.settings.livemode, event["type"]),
                ).fetchone()
                if claimed:
                    self.sync(db, account)
        return {"received": True}
