"""Real PostgreSQL + fake Stripe transport, real signature verification, no external calls."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import hashlib
import hmac
import json
import time
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest
from fastapi.testclient import TestClient
from app_core.auth.identity import _principal_from_access
from app_core.billing import BillingService
from app_core.main import create_app, HASHER
from app_core.plan_admin import configure
from app_core.stripe_gateway import StripeGateway, StripeSettings, validate_price

stripe = pytest.importorskip("stripe")


class FakeStripe:
    verify_event = StripeGateway.verify_event

    def __init__(self, settings):
        self.settings = settings
        self.customers = {}
        self.sessions = {}
        self.subs = {}
        self.lines = {}
        self.checkout_calls = 0
        self.sync_calls = 0
        self.fail_sync = False
        self.fail_after_checkout = False
        self.prices = {
            key: {
                "id": key,
                "livemode": False,
                "active": True,
                "type": "recurring",
                "billing_scheme": "per_unit",
                "unit_amount": amount,
                "currency": "usd",
                "recurring": {
                    "usage_type": "licensed",
                    "interval": "month",
                    "interval_count": 1,
                },
            }
            for key, amount in [("price_pro", 2000), ("price_enterprise", 5000)]
        }

    def price(self, key):
        return deepcopy(self.prices[key])

    def create_customer(self, key):
        self.customers.setdefault(key, {"id": "cus_" + key, "livemode": False})
        return deepcopy(self.customers[key])

    def checkout(self, attempt, customer):
        self.checkout_calls += 1
        self.sessions.setdefault(
            attempt["id"],
            {
                "id": "cs_" + attempt["id"],
                "customer": customer,
                "livemode": False,
                "client_reference_id": attempt["id"],
                "mode": "subscription",
                "status": "open",
                "url": "https://checkout.stripe.com/c/pay/" + attempt["id"],
            },
        )
        if self.fail_after_checkout:
            self.fail_after_checkout = False
            raise ConnectionError("ambiguous response after Stripe accepted create")
        return deepcopy(self.sessions[attempt["id"]])

    def session(self, key):
        return deepcopy(next(s for s in self.sessions.values() if s["id"] == key))

    def find_session(self, customer, attempt_id):
        session = self.sessions.get(attempt_id)
        return (
            deepcopy(session) if session and session["customer"] == customer else None
        )

    def subscriptions(self, customer):
        self.sync_calls += 1
        if self.fail_sync:
            raise ConnectionError("Stripe unavailable")
        return [deepcopy(s) for s in self.subs.values() if s["customer"] == customer]

    def subscription(self, key):
        return deepcopy(self.subs[key])

    def invoice_lines(self, key):
        return deepcopy(self.lines[key])

    def portal(self, customer):
        return {"url": "https://billing.stripe.com/p/session/" + customer}

    def activate(self, customer, key="sub_one", status="active", price="price_pro"):
        self.subs[key] = {
            "id": key,
            "customer": customer,
            "livemode": False,
            "status": status,
            "items": {
                "data": [
                    {
                        "id": "si_" + key,
                        "price": {"id": price},
                        "quantity": 1,
                        "current_period_end": int(time.time()) + 3600,
                    }
                ]
            },
            "cancel_at_period_end": False,
            "latest_invoice": {
                "id": "in_" + key,
                "status": "paid",
                "customer": customer,
                "livemode": False,
            },
        }
        self.lines["in_" + key] = [
            {
                "livemode": False,
                "amount": 2000,
                "parent": {
                    "subscription_item_details": {
                        "subscription": key,
                        "subscription_item": "si_" + key,
                    }
                },
                "pricing": {"price_details": {"price": price}},
                "period": {
                    "end": self.subs[key]["items"]["data"][0]["current_period_end"]
                },
            }
        ]
        return self.subs[key]


@pytest.fixture
def billing(pg_store, monkeypatch):
    store, operator = pg_store
    with psycopg.connect(operator) as db:
        db.execute("""DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='starter_billing') THEN
            CREATE ROLE starter_billing LOGIN PASSWORD 'billing-test-only' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
            END IF; END $$; GRANT app_billing_service TO starter_billing;""")
    config = conninfo_to_dict(store.database_url)
    config.update(user="starter_billing", password="billing-test-only")
    settings = StripeSettings(
        "sk_test_fake", "whsec_test", make_conninfo(**config), "http://localhost:5173"
    )
    for key, value in {
        "BILLING_ENABLED": "true",
        "STRIPE_ENABLED": "true",
        "STRIPE_MODE": "test",
        "STRIPE_SECRET_KEY": settings.secret_key,
        "STRIPE_WEBHOOK_SECRET": settings.webhook_secret,
        "BILLING_DATABASE_URL": settings.database_url,
        "APP_PUBLIC_URL": settings.public_url,
    }.items():
        monkeypatch.setenv(key, value)
    fake = FakeStripe(settings)
    service = BillingService(settings, fake)
    hashed = HASHER.hash("billing-test-password")
    users = {}
    for email, workspace, role in [
        ("admin@test.com", "alpha", "admin"),
        ("editor@test.com", "alpha", "editor"),
        ("viewer@test.com", "alpha", "viewer"),
        ("other@test.com", "beta", "admin"),
    ]:
        users[email] = store.provision(email, hashed, workspace, workspace, role)
    for key in ["pro", "enterprise"]:
        configure(operator, "map-price", key=key, price_id="price_" + key, gateway=fake)
    app = create_app(store, billing_service=service)
    clients = {}
    for email, workspace in [
        ("admin@test.com", "alpha"),
        ("editor@test.com", "alpha"),
        ("viewer@test.com", "alpha"),
        ("other@test.com", "beta"),
    ]:
        c = TestClient(app, headers={"X-App-Request": "1", "X-Workspace": workspace})
        assert (
            c.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "billing-test-password"},
            ).status_code
            == 200
        )
        clients[email.split("@")[0]] = c
    principal = _principal_from_access(
        store.get_active_global_access(users["admin@test.com"], "alpha")
    )
    return store, operator, service, fake, clients, principal


def signed(
    client,
    fake,
    customer,
    event_id="evt_1",
    event_type="customer.subscription.updated",
    **changes,
):
    event = {
        "id": event_id,
        "type": event_type,
        "livemode": False,
        "created": 100,
        "data": {
            "object": {
                "customer": customer,
                "status": "ignored",
                "metadata": {"workspace": "beta"},
            }
        },
        **changes,
    }
    payload = json.dumps(event).encode()
    stamp = int(time.time())
    signature = hmac.new(
        fake.settings.webhook_secret.encode(),
        str(stamp).encode() + b"." + payload,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/api/v1/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": f"t={stamp},v1={signature}"},
    )


def begin(billing):
    _, _, _, fake, clients, _ = billing
    response = clients["admin"].post("/api/v1/billing/checkout", json={"plan": "pro"})
    assert response.status_code == 200, response.text
    return next(iter(fake.customers.values()))["id"]


def test_checkout_authorization_input_and_concurrency(billing):
    store, _, service, fake, clients, principal = billing
    for name in ("editor", "viewer"):
        for endpoint, body in [
            ("checkout", {"plan": "pro"}),
            ("portal", {}),
            ("refresh", {}),
        ]:
            assert (
                clients[name].post("/api/v1/billing/" + endpoint, json=body).status_code
                == 403
            )
    assert (
        clients["other"]
        .get("/api/v1/billing", headers={"X-Workspace": "alpha"})
        .status_code
        == 404
    )
    assert (
        clients["admin"]
        .post(
            "/api/v1/billing/checkout",
            json={"plan": "pro", "price_id": "price_attacker"},
        )
        .status_code
        == 422
    )
    assert (
        clients["admin"]
        .post("/api/v1/billing/checkout", json={"plan": "missing"})
        .status_code
        == 404
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda _: service.checkout(principal, "pro"), range(2))
        )
    assert responses[0] == responses[1]
    assert fake.checkout_calls == 1
    assert clients["admin"].get("/api/v1/entitlements").json()["features"] == []
    assert (
        clients["admin"]
        .post("/api/v1/billing/checkout", json={"plan": "enterprise"})
        .status_code
        == 409
    )
    with store.connection(principal) as db:
        assert len(db.execute("SELECT * FROM billing_accounts").fetchall()) == 1
    with store.connection() as db:
        assert db.execute("SELECT * FROM billing_accounts").fetchall() == []


def test_checkout_ambiguous_response_recovery_and_expiry(billing):
    _, _, _, fake, clients, _ = billing
    fake.fail_after_checkout = True
    assert (
        clients["admin"]
        .post("/api/v1/billing/checkout", json={"plan": "pro"})
        .status_code
        == 503
    )
    assert (
        clients["admin"]
        .post("/api/v1/billing/checkout", json={"plan": "pro"})
        .status_code
        == 200
    )
    assert fake.checkout_calls == 1
    next(iter(fake.sessions.values()))["status"] = "expired"
    assert (
        clients["admin"]
        .post("/api/v1/billing/checkout", json={"plan": "enterprise"})
        .status_code
        == 200
    )
    assert fake.checkout_calls == 2


def test_signed_webhook_lifecycle_duplicate_reordered_and_missed_expiry(billing):
    store, _, service, fake, clients, principal = billing
    customer = begin(billing)
    subscription = fake.activate(customer)
    public = TestClient(clients["admin"].app)  # Deliberately no auth or CSRF header.
    assert signed(public, fake, customer).status_code == 200
    assert clients["admin"].get("/api/v1/entitlements").json()["plan"] == "pro"
    assert (
        clients["viewer"]
        .post("/api/v1/records", json={"title": "role still denied"})
        .status_code
        == 403
    )
    before = fake.sync_calls
    assert signed(public, fake, customer).status_code == 200
    assert fake.sync_calls == before
    subscription["status"] = "past_due"
    assert (
        signed(public, fake, customer, "evt_2", "invoice.payment_failed").status_code
        == 200
    )
    assert clients["admin"].get("/api/v1/entitlements").json()["features"] == []
    # Older payload, same-second created timestamp: current provider state wins.
    assert (
        signed(
            public, fake, customer, "evt_old", "customer.subscription.created"
        ).status_code
        == 200
    )
    assert clients["admin"].get("/api/v1/entitlements").json()["features"] == []
    assert clients["admin"].post("/api/v1/billing/portal").status_code == 200
    subscription["status"] = "active"
    subscription["cancel_at_period_end"] = True
    assert clients["admin"].post("/api/v1/billing/refresh").status_code == 200
    assert clients["admin"].get("/api/v1/entitlements").json()["plan"] == "pro"
    with service.connection(principal.tenant_id) as db:
        db.execute(
            "UPDATE billing_subscriptions SET period_end=now()-interval '1 second'"
        )
    assert clients["admin"].get("/api/v1/entitlements").json()["features"] == []
    subscription["status"] = "canceled"
    assert (
        signed(
            public, fake, customer, "evt_cancel", "customer.subscription.deleted"
        ).status_code
        == 200
    )
    assert store.workspace_entitlements(principal, True)[0] is None


@pytest.mark.parametrize(
    "status",
    ["incomplete", "incomplete_expired", "unpaid", "paused", "past_due", "canceled"],
)
def test_non_entitling_statuses(billing, status):
    _, _, _, fake, clients, _ = billing
    customer = begin(billing)
    fake.activate(customer, status=status)
    assert clients["admin"].post("/api/v1/billing/refresh").status_code == 200
    assert clients["admin"].get("/api/v1/entitlements").json()["features"] == []


def test_trial_plan_changes_unmapped_duplicate_and_manual_override(billing):
    _, operator, _, fake, clients, _ = billing
    customer = begin(billing)
    sub = fake.activate(customer, status="trialing")
    sub["trial_end"] = int(time.time()) + 1000
    assert (
        clients["admin"].post("/api/v1/billing/refresh").json()["entitlements"]["plan"]
        == "pro"
    )
    sub["items"]["data"][0]["price"]["id"] = "price_enterprise"
    assert (
        clients["admin"].post("/api/v1/billing/refresh").json()["entitlements"]["plan"]
        == "enterprise"
    )
    sub["items"]["data"][0]["price"]["id"] = "price_unknown"
    assert (
        clients["admin"]
        .post("/api/v1/billing/refresh")
        .json()["entitlements"]["features"]
        == []
    )
    sub["items"]["data"][0]["price"]["id"] = "price_pro"
    fake.activate(customer, key="sub_duplicate")
    assert (
        clients["admin"]
        .post("/api/v1/billing/refresh")
        .json()["entitlements"]["features"]
        == []
    )
    configure(operator, "assign", workspace="alpha", key="enterprise")
    assert clients["admin"].get("/api/v1/entitlements").json()["plan"] == "enterprise"
    assert (
        clients["admin"]
        .post("/api/v1/billing/checkout", json={"plan": "pro"})
        .status_code
        == 409
    )


def test_signature_mode_csrf_and_retry_atomicity(billing):
    _, _, service, fake, clients, principal = billing
    customer = begin(billing)
    fake.activate(customer)
    public = TestClient(clients["admin"].app)
    assert public.post("/api/v1/billing/webhook", content=b"{}").status_code == 400
    assert (
        public.post("/api/v1/billing/webhook", content=b"x" * 262145).status_code == 413
    )
    assert signed(public, fake, customer, livemode=True).status_code == 400
    assert signed(public, fake, customer, account="acct_foreign").status_code == 400
    assert (
        public.post("/api/v1/billing/checkout", json={"plan": "pro"}).status_code == 403
    )
    fake.fail_sync = True
    assert signed(public, fake, customer).status_code == 503
    with service.connection(principal.tenant_id) as db:
        assert db.execute("SELECT * FROM billing_events").fetchall() == []
    fake.fail_sync = False
    assert signed(public, fake, customer).status_code == 200
    # Signed arbitrary metadata/customer cannot claim another workspace.
    assert signed(public, fake, "cus_unknown", "evt_unknown").status_code == 200
    assert clients["other"].get("/api/v1/entitlements").json()["features"] == []


def test_billing_database_privilege_boundary(billing):
    store, operator, service, _, _, principal = billing
    with pytest.raises(RuntimeError, match="separate restricted"):
        BillingService(
            replace(service.settings, database_url=operator), service.gateway
        )
    for statement in [
        "UPDATE billing_subscriptions SET status='active'",
        "UPDATE billing_prices SET plan_key='enterprise'",
        "SET ROLE app_billing_service",
    ]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with store.connection(principal) as db:
                db.execute(statement)
    for statement in [
        "UPDATE workspace_plans SET plan_key='enterprise'",
        "UPDATE plans SET active=true",
        "UPDATE memberships SET role='admin'",
    ]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with service.connection() as db:
                db.execute(statement)


def test_configuration_and_price_guards(billing, monkeypatch):
    _, operator, service, fake, _, _ = billing
    with pytest.raises(ValueError, match="remapped"):
        configure(
            operator, "map-price", key="enterprise", price_id="price_pro", gateway=fake
        )
    with pytest.raises(ValueError):
        validate_price({**fake.price("price_pro"), "livemode": True}, False)
    monkeypatch.setenv("STRIPE_MODE", "live")
    with pytest.raises(RuntimeError, match="explicit"):
        StripeSettings.from_env()
    monkeypatch.setenv("STRIPE_ALLOW_LIVE", "true")
    with pytest.raises(RuntimeError, match="does not match"):
        StripeSettings.from_env()
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_fake")
    with pytest.raises(RuntimeError, match="HTTPS"):
        StripeSettings.from_env()


def test_portal_binds_customer_and_service_rechecks_stale_admin(billing):
    store, _, service, fake, clients, principal = billing
    customer = begin(billing)
    assert (
        clients["other"]
        .post("/api/v1/billing/checkout", json={"plan": "pro"})
        .status_code
        == 200
    )
    other_customer = next(
        c["id"] for c in fake.customers.values() if c["id"] != customer
    )
    portal = clients["admin"].post(
        "/api/v1/billing/portal", json={"customer": other_customer, "workspace": "beta"}
    )
    assert portal.status_code == 200
    assert portal.json()["url"].endswith(customer)
    with store.connection() as db:
        db.execute(
            "UPDATE memberships SET role='viewer' WHERE user_id=%s AND workspace_id=%s",
            (principal.subject, principal.tenant_id),
        )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        service.portal(principal)
    assert error.value.status_code == 403


def test_concurrent_duplicate_webhook_is_applied_once(billing):
    _, _, service, fake, _, _ = billing
    customer = begin(billing)
    fake.activate(customer)
    before = fake.sync_calls
    event = {
        "id": "evt_concurrent",
        "type": "invoice.paid",
        "livemode": False,
        "data": {"object": {"customer": customer}},
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.webhook(event), range(2)))
    assert results == [{"received": True}, {"received": True}]
    assert fake.sync_calls == before + 1


def test_real_signature_rejects_stale_and_tampered():
    settings = StripeSettings("sk_test_fake", "whsec_test", "", "http://localhost:5173")
    fake = FakeStripe(settings)
    payload = b'{"id":"evt_test"}'
    old = int(time.time()) - 301
    sig = hmac.new(
        b"whsec_test", str(old).encode() + b"." + payload, hashlib.sha256
    ).hexdigest()
    with pytest.raises(stripe.SignatureVerificationError):
        fake.verify_event(payload, f"t={old},v1={sig}")
    with pytest.raises(stripe.SignatureVerificationError):
        fake.verify_event(payload + b" ", f"t={int(time.time())},v1={sig}")


def test_active_unpaid_or_uninvoiced_upgrade_never_grants_new_plan(billing):
    _, _, _, fake, clients, _ = billing
    customer = begin(billing)
    sub = fake.activate(customer)
    admin = clients["admin"]
    assert admin.post("/api/v1/billing/refresh").json()["entitlements"]["plan"] == "pro"
    sub["pending_update"] = {"subscription_items": [{"price": "price_enterprise"}]}
    assert (
        admin.post("/api/v1/billing/refresh").json()["entitlements"]["features"] == []
    )
    sub["pending_update"] = None
    sub["items"]["data"][0]["price"]["id"] = "price_enterprise"
    # Old invoice paid only for Pro: an uninvoiced upgrade remains denied.
    assert (
        admin.post("/api/v1/billing/refresh").json()["entitlements"]["features"] == []
    )
    fake.lines["in_sub_one"][0]["pricing"]["price_details"]["price"] = (
        "price_enterprise"
    )
    sub["latest_invoice"]["status"] = "open"
    assert (
        admin.post("/api/v1/billing/refresh").json()["entitlements"]["features"] == []
    )
    sub["latest_invoice"]["status"] = "paid"
    assert (
        admin.post("/api/v1/billing/refresh").json()["entitlements"]["plan"]
        == "enterprise"
    )
