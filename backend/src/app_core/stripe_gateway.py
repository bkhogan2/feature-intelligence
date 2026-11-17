"""Small official-SDK boundary. No Stripe credentials enter agent subprocesses."""

from dataclasses import dataclass, field
import os
from urllib.parse import urlparse

API_VERSION = "2026-10-28.endive"


def boolean(name, default="false"):
    value = os.getenv(name, default).lower()
    if value not in {"true", "false"}:
        raise RuntimeError(f"{name} must be true or false")
    return value == "true"


@dataclass(frozen=True)
class StripeSettings:
    secret_key: str = field(repr=False)
    webhook_secret: str = field(repr=False)
    database_url: str = field(repr=False)
    public_url: str
    livemode: bool = False
    portal_configuration: str | None = None

    @classmethod
    def from_env(cls):
        if not boolean("STRIPE_ENABLED"):
            return None
        if not boolean("BILLING_ENABLED"):
            raise RuntimeError("Stripe requires BILLING_ENABLED=true")
        mode = os.getenv("STRIPE_MODE", "test")
        if mode not in {"test", "live"}:
            raise RuntimeError("STRIPE_MODE must be test or live")
        live = mode == "live"
        if live and not boolean("STRIPE_ALLOW_LIVE"):
            raise RuntimeError("Live Stripe requires explicit STRIPE_ALLOW_LIVE=true")
        key = os.getenv("STRIPE_SECRET_KEY", "")
        if not key.startswith((f"sk_{mode}_", f"rk_{mode}_")):
            raise RuntimeError("Stripe secret key does not match STRIPE_MODE")
        secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
        dsn = os.getenv("BILLING_DATABASE_URL", "")
        url = os.getenv("APP_PUBLIC_URL", "").rstrip("/")
        parsed = urlparse(url)
        local = parsed.hostname in {"localhost", "127.0.0.1"}
        if (
            not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or (
                parsed.scheme != "https"
                and not (not live and local and parsed.scheme == "http")
            )
        ):
            raise RuntimeError(
                "APP_PUBLIC_URL must be a trusted HTTPS origin (localhost HTTP allowed in test mode)"
            )
        if not secret.startswith("whsec_") or not dsn:
            raise RuntimeError(
                "Set STRIPE_WEBHOOK_SECRET and separate BILLING_DATABASE_URL"
            )
        return cls(
            key,
            secret,
            dsn,
            url,
            live,
            os.getenv("STRIPE_PORTAL_CONFIGURATION") or None,
        )


class StripeGateway:
    def __init__(self, settings):
        import stripe

        self.settings = settings
        self.client = stripe.StripeClient(
            settings.secret_key,
            stripe_version=API_VERSION,
            max_network_retries=1,
            http_client=stripe.RequestsClient(timeout=10),
        )

    def verify_event(self, payload, signature):
        import stripe

        return stripe.Webhook.construct_event(
            payload, signature, self.settings.webhook_secret, tolerance=300
        )

    def price(self, price_id):
        return self.client.v1.prices.retrieve(price_id)

    def create_customer(self, request_id):
        return self.client.v1.customers.create(
            {}, options={"idempotency_key": "customer-" + request_id}
        )

    def subscriptions(self, customer):
        return list(
            self.client.v1.subscriptions.list(
                {"customer": customer, "status": "all", "limit": 100}
            ).auto_paging_iter()
        )

    def subscription(self, subscription):
        return self.client.v1.subscriptions.retrieve(
            subscription, {"expand": ["latest_invoice"]}
        )

    def invoice_lines(self, invoice):
        return list(
            self.client.v1.invoices.line_items.list(
                invoice, {"limit": 100}
            ).auto_paging_iter()
        )

    def checkout(self, attempt, customer):
        return self.client.v1.checkout.sessions.create(
            {
                "customer": customer,
                "mode": "subscription",
                "line_items": [{"price": attempt["price_id"], "quantity": 1}],
                "client_reference_id": attempt["id"],
                "success_url": attempt["return_url"] + "/#settings?billing=return",
                "cancel_url": attempt["return_url"] + "/#settings?billing=cancel",
                "expires_at": attempt["expires_at"],
            },
            options={"idempotency_key": "checkout-" + attempt["id"]},
        )

    def session(self, session_id):
        return self.client.v1.checkout.sessions.retrieve(session_id)

    def find_session(self, customer, attempt_id):
        for session in self.client.v1.checkout.sessions.list(
            {"customer": customer, "limit": 100}
        ).auto_paging_iter():
            if session.get("client_reference_id") == attempt_id:
                return session
        return None

    def portal(self, customer):
        params = {
            "customer": customer,
            "return_url": self.settings.public_url + "/#settings?billing=return",
        }
        if self.settings.portal_configuration:
            params["configuration"] = self.settings.portal_configuration
        return self.client.v1.billing_portal.sessions.create(params)


def validate_price(price, livemode):
    recurring = price.get("recurring") or {}
    if (
        price.get("livemode") is not livemode
        or not price.get("active")
        or price.get("type") != "recurring"
        or recurring.get("usage_type") != "licensed"
        or price.get("billing_scheme") != "per_unit"
        or price.get("unit_amount") is None
        or price.get("transform_quantity")
        or recurring.get("interval") not in {"day", "week", "month", "year"}
    ):
        raise ValueError(
            "Only active, same-mode fixed recurring licensed prices are supported"
        )
    return {
        "currency": price["currency"],
        "unit_amount": price["unit_amount"],
        "interval": recurring["interval"],
        "interval_count": recurring["interval_count"],
    }
