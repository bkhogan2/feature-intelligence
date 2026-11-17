from uuid import uuid4
import pytest
from test_feedback import feedback_setup as shared_feedback_setup
from test_triage import principal, seed_opportunity


@pytest.fixture
def setup(pg_store):
    return shared_feedback_setup.__wrapped__(pg_store)


def test_status_before_limit_and_workspace_scope(setup):
    store, ids, client, _ = setup
    p = principal(store, ids)
    old = seed_opportunity(store, p, "Older shipped")
    with store.connection(p) as db:
        db.execute(
            "UPDATE opportunities SET status='shipped' WHERE id=%s",
            (old,),
        )
        for i in range(35):
            db.execute(
                "INSERT INTO opportunities(id,workspace_id,name,problem,created_by) VALUES(%s,%s,%s,%s,%s)",
                (uuid4(), p.tenant_id, f"Newer {i}", "Problem", p.subject),
            )
    other = seed_opportunity(
        store, principal(store, ids, workspace="beta"), "Other workspace"
    )
    c = client("admin")
    all_rows = c.get("/api/v1/opportunities").json()
    assert len(all_rows["items"]) == 30 and all_rows["has_more"]
    assert old not in [r["id"] for r in all_rows["items"]]
    filtered = c.get("/api/v1/opportunities?status=shipped").json()
    assert [r["id"] for r in filtered["items"]] == [old] and not filtered["has_more"]
    assert c.get("/api/v1/opportunities?status=planned").json()["items"] == []
    assert c.get("/api/v1/opportunities?status=invalid").status_code == 422
    assert (
        client("viewer").get("/api/v1/opportunities?status=shipped").json() == filtered
    )
    assert other not in [
        r["id"]
        for r in c.get("/api/v1/opportunities?status=considering").json()["items"]
    ]
    assert (
        c.get("/api/v1/opportunities?status=shipped&search=absent").json()["items"]
        == []
    )


def test_opportunity_pagination_keeps_filters_and_tenant_scope(setup):
    store, ids, client, _ = setup
    p = principal(store, ids)
    expected = {seed_opportunity(store, p, f"Paged {i}") for i in range(5)}
    seed_opportunity(store, p, "Unrelated")
    seed_opportunity(store, principal(store, ids, workspace="beta"), "Paged private")
    c = client("admin")
    observed = []
    for offset in (0, 2, 4):
        response = c.get(f"/api/v1/opportunities?search=Paged&limit=2&offset={offset}")
        assert response.status_code == 200
        page = response.json()
        observed.extend(item["id"] for item in page["items"])
        assert page["has_more"] == (offset < 4)
    assert len(observed) == len(set(observed)) == 5
    assert set(observed) == expected
    for query in ("limit=0", "limit=101", "offset=-1", "offset=100001"):
        assert c.get(f"/api/v1/opportunities?{query}").status_code == 422
