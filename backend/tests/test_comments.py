"""Request discussions persist and respect workspace membership."""

import pytest
from test_feedback import feedback_setup as shared_feedback_setup
from test_triage import make_request
from uuid import uuid4


@pytest.fixture
def setup(pg_store):
    return shared_feedback_setup.__wrapped__(pg_store)


def test_comments_scope_permissions_retry_and_validation(setup):
    _, _, client, _ = setup
    admin = client("admin")
    item = make_request(admin)
    path = f"/api/v1/feedback/{item['id']}/comments"
    payload = {
        "id": str(uuid4()),
        "body": "**Useful** feedback\n\nFollow up with the customer.",
    }
    assert client("viewer").post(path, json=payload).status_code == 403
    assert client("admin", "beta").get(path).status_code == 404
    assert client("admin", "beta").post(path, json=payload).status_code == 404
    saved = admin.post(path, json=payload)
    assert saved.status_code == 201, saved.text
    assert saved.json()["body"] == payload["body"]
    assert admin.post(path, json=payload).status_code == 201
    assert admin.post(path, json={**payload, "body": "different"}).status_code == 409
    assert client("viewer").get(path).status_code == 403
    assert len(client("editor").get(path).json()["items"]) == 1
    assert admin.post(path, json={"id": str(uuid4()), "body": "   "}).status_code == 422
    assert (
        admin.post(path, json={"id": str(uuid4()), "body": "x" * 10001}).status_code
        == 422
    )
    admin.patch("/api/v1/feedback/bulk", json={"ids": [item["id"]], "archived": True})
    assert len(admin.get(path).json()["items"]) == 1
