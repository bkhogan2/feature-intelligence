import pytest
from uuid import uuid4
from test_feedback import feedback_setup as shared_feedback_setup
from test_triage import make_request, principal, seed_opportunity


@pytest.fixture
def setup(pg_store):
    return shared_feedback_setup.__wrapped__(pg_store)


def test_multiple_links_manual_approval_scope_and_stale_edits(setup):
    store, ids, client, _ = setup
    c = client("admin")
    request = make_request(c)
    p = principal(store, ids)
    a, b = seed_opportunity(store, p, "First"), seed_opportunity(store, p, "Second")
    path = f"/api/v1/feedback/{request['id']}/opportunities"
    payload = {"opportunity_ids": [a, b], "expected_ids": [], "approve": True}
    assert client("viewer").put(path, json=payload).status_code == 403
    assert client("admin", "beta").put(path, json=payload).status_code == 404
    assert (
        c.put(path, json={**payload, "opportunity_ids": [a, str(uuid4())]}).status_code
        == 404
    )
    assert c.put(path, json=payload).status_code == 200
    state = c.get(f"/api/v1/feedback/{request['id']}/triage").json()
    assert {x["id"] for x in state["linked_opportunities"]} == {a, b}
    for target in [a, b]:
        assert len(c.get(f"/api/v1/opportunities/{target}").json()["feedback"]) == 1
    assert c.put(path, json=payload).status_code == 409
    assert (
        c.put(path, json={"opportunity_ids": [b], "expected_ids": [a, b]}).status_code
        == 200
    )
    assert len(c.get(f"/api/v1/opportunities/{a}").json()["feedback"]) == 0
    assert (
        c.put(path, json={"opportunity_ids": [], "expected_ids": [b]}).status_code
        == 409
    )
    c.patch("/api/v1/feedback/bulk", json={"ids": [request["id"]], "archived": True})
    assert (
        c.put(path, json={"opportunity_ids": [a, b], "expected_ids": [b]}).status_code
        == 409
    )
    assert (
        len(
            c.get(f"/api/v1/feedback/{request['id']}/triage").json()[
                "linked_opportunities"
            ]
        )
        == 1
    )


def test_reject_reopen_status_permissions_and_archive_restore(setup):
    store, ids, client, _ = setup
    c = client("admin")
    request = make_request(c)
    path = f"/api/v1/feedback/{request['id']}/status"
    payload = {"status": "rejected", "expected_status": "new"}
    assert client("viewer").put(path, json=payload).status_code == 403
    assert client("admin", "beta").put(path, json=payload).status_code == 404
    assert c.put(path, json=payload).status_code == 200
    assert c.put(path, json=payload).status_code == 409
    assert c.put(path, json={"status": "approved", "expected_status": "rejected"}).status_code == 422
    assert c.patch("/api/v1/feedback/bulk", json={"ids": [request["id"]], "archived": True}).status_code == 200
    assert c.put(path, json={"status":"new", "expected_status":"archived"}).status_code == 409
    assert c.patch("/api/v1/feedback/bulk", json={"ids": [request["id"]], "archived": False}).status_code == 200
    assert c.put(path, json={"status":"new", "expected_status":"rejected"}).status_code == 200
