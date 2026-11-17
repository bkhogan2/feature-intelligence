"""Bulk edits use real PostgreSQL transactions and existing lifecycle history."""

from uuid import uuid4
import pytest
from test_feedback import feedback_setup as shared_feedback_setup
from test_triage import make_request, principal, seed_opportunity


@pytest.fixture
def setup(pg_store):
    return shared_feedback_setup.__wrapped__(pg_store)


def test_feedback_bulk_scope_restore_priority_and_atomicity(setup):
    store, ids, client, _ = setup
    c = client("admin")
    item = make_request(c)
    path = "/api/v1/feedback/bulk"
    payload = {"ids": [item["id"]], "archived": True, "priority": "high"}
    assert client("viewer").patch(path, json=payload).status_code == 403
    assert client("admin", "beta").patch(path, json=payload).status_code == 404
    result = c.patch(path, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["items"][0]["status"] == "archived"
    assert result.json()["items"][0]["priority"] == "high"
    # Triage can complete while a request is archived; restore its latest lifecycle.
    with store.connection(principal(store, ids)) as db:
        db.execute("UPDATE feedback SET status='triaged' WHERE id=%s", (item["id"],))
    archived = c.get("/api/v1/feedback?status=archived").json()["items"][0]
    assert archived["archived_from_status"] == "triaged"
    assert (
        c.patch(
            path, json={"ids": [item["id"], str(uuid4())], "priority": "low"}
        ).status_code
        == 404
    )
    restored = c.patch(path, json={"ids": [item["id"]], "archived": False}).json()[
        "items"
    ][0]
    assert restored["status"] == "triaged" and restored["priority"] == "high"
    assert (
        c.patch(path, json={"ids": [item["id"]], "priority": None}).json()["items"][0][
            "priority"
        ]
        is None
    )
    assert (
        c.patch(
            path, json={"ids": [item["id"], item["id"]], "archived": True}
        ).status_code
        == 422
    )


def test_opportunity_bulk_and_board_atomic_history(setup):
    store, ids, client, _ = setup
    p = principal(store, ids)
    a, b = seed_opportunity(store, p, "A"), seed_opportunity(store, p, "B")
    c = client("admin")
    path = "/api/v1/opportunities/bulk"
    change = {
        "ids": [a, b],
        "status": "planned",
        "expected_statuses": {a: "considering", b: "shipped"},
    }
    assert c.patch(path, json=change).status_code == 409
    assert c.get(f"/api/v1/opportunities/{a}").json()["status"] == "considering"
    assert c.get(f"/api/v1/opportunities/{a}").json()["decisions"] == []
    change["expected_statuses"][b] = "considering"
    assert c.patch(path, json=change).status_code == 200
    board = {
        "items": [
            {
                "id": a,
                "status": "in_progress",
                "expected_status": "planned",
                "order": 1,
            },
            {"id": b, "status": "planned", "expected_status": "planned", "order": 0},
        ]
    }
    assert (
        client("viewer").post("/api/v1/opportunities/board", json=board).status_code
        == 403
    )
    assert (
        client("admin", "beta")
        .post("/api/v1/opportunities/board", json=board)
        .status_code
        == 404
    )
    result = c.post("/api/v1/opportunities/board", json=board)
    assert result.status_code == 200, result.text
    detail = c.get(f"/api/v1/opportunities/{a}").json()
    assert detail["status"] == "in_progress" and detail["board_order"] == 1
    assert len(detail["decisions"]) == 2
    assert c.post("/api/v1/opportunities/board", json=board).status_code == 409
    assert c.patch(path, json={"ids": [a], "archived": True}).status_code == 200
    assert a not in [
        row["id"] for row in c.get("/api/v1/opportunities").json()["items"]
    ]
    assert a in [
        row["id"]
        for row in c.get("/api/v1/opportunities?include_archived=true").json()["items"]
    ]
    assert c.patch(path, json={"ids": [a], "archived": False}).status_code == 200
    assert c.get(f"/api/v1/opportunities/{a}").json()["status"] == "in_progress"
