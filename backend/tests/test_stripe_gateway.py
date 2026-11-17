"""Exercise official SDK request serialization without a network transport."""

import json
from urllib.parse import parse_qs, urlparse
import pytest
from app_core.stripe_gateway import StripeGateway, StripeSettings, API_VERSION

stripe = pytest.importorskip("stripe")


class Transport(stripe.HTTPClient):
    name = "test-transport"

    def __init__(self):
        super().__init__()
        self.calls = []
        self.response = {}

    def request(self, method, url, headers, post_data=None, **kwargs):
        self.calls.append((method, url, headers, post_data))
        return json.dumps(self.response), 200, {"request-id": "req_test"}


def test_official_sdk_serializes_fixed_checkout_and_portal_requests(monkeypatch):
    transport = Transport()
    monkeypatch.setattr(stripe, "RequestsClient", lambda **kwargs: transport)
    gateway = StripeGateway(
        StripeSettings(
            "sk_test_not_real", "whsec_not_real", "", "http://localhost:5173"
        )
    )
    transport.response = {"id": "cus_test", "object": "customer", "livemode": False}
    gateway.create_customer("customer-attempt")
    assert transport.calls[-1][2]["Idempotency-Key"] == "customer-customer-attempt"
    transport.response = {
        "id": "cs_test",
        "object": "checkout.session",
        "url": "https://checkout.stripe.com/test",
    }
    gateway.checkout(
        {
            "id": "attempt-one",
            "price_id": "price_registered",
            "expires_at": 2000000000,
            "return_url": "https://app.example.com",
        },
        "cus_test",
    )
    method, url, headers, body = transport.calls[-1]
    assert method == "post"
    assert urlparse(url).path == "/v1/checkout/sessions"
    assert headers["Stripe-Version"] == API_VERSION
    assert headers["Idempotency-Key"] == "checkout-attempt-one"
    fields = parse_qs(body)
    assert fields["mode"] == ["subscription"]
    assert fields["customer"] == ["cus_test"]
    assert fields["line_items[0][price]"] == ["price_registered"]
    assert fields["line_items[0][quantity]"] == ["1"]
    assert fields["success_url"] == ["https://app.example.com/#settings?billing=return"]
    assert fields["client_reference_id"] == ["attempt-one"]
    transport.response = {
        "object": "billing_portal.session",
        "id": "bps_test",
        "url": "https://billing.stripe.com/test",
    }
    gateway.portal("cus_test")
    assert urlparse(transport.calls[-1][1]).path == "/v1/billing_portal/sessions"
    assert parse_qs(transport.calls[-1][3])["customer"] == ["cus_test"]
    transport.response = {"object": "subscription", "id": "sub_test"}
    gateway.subscription("sub_test")
    assert parse_qs(urlparse(transport.calls[-1][1]).query)["expand[0]"] == [
        "latest_invoice"
    ]
    transport.response = {
        "object": "list",
        "data": [],
        "has_more": False,
        "url": "/v1/invoices/in_test/lines",
    }
    assert gateway.invoice_lines("in_test") == []
    assert urlparse(transport.calls[-1][1]).path == "/v1/invoices/in_test/lines"
