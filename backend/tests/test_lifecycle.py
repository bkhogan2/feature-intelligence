"""Lifecycle integration against isolated PostgreSQL, no model calls."""

from uuid import UUID

import psycopg
import pytest

from test_triage import make_request, principal, output, seed_opportunity
from test_feedback import feedback_setup as shared_feedback_setup


@pytest.fixture
def triage_setup(pg_store):
    return shared_feedback_setup.__wrapped__(pg_store)


def approve(store, p, item):
    run, _ = store.start_triage(p, UUID(item["id"]), "test", "test", 120)
    store.finish_triage(p, run["id"], output(item))
    return run


def test_approval_moves_inbox_preserves_evidence_and_is_idempotent(triage_setup):
    store, ids, client, _ = triage_setup
    c = client("admin")
    p = principal(store, ids)
    item = make_request(c)
    run = approve(store, p, item)
    assert c.get("/api/v1/feedback?status=new").json()["items"][0]["id"] == item["id"]
    path = f"/api/v1/feedback/{item['id']}/triage/{run['id']}/confirm"
    assert client("viewer").post(path).status_code == 403
    assert client("admin", "beta").post(path).status_code == 404
    response = c.post(path)
    assert response.status_code == 200
    assert c.post(path).json() == response.json()
    assert c.get("/api/v1/feedback?status=new").json()["items"] == []
    triaged = c.get("/api/v1/feedback?status=triaged").json()["items"]
    assert len(triaged) == 1 and triaged[0]["description"] == item["description"]
    assert c.get("/api/v1/feedback?status=all").json()["items"] == triaged
    assert c.get("/api/v1/feedback?status=invalid").status_code == 422
    opportunity = c.get(
        "/api/v1/opportunities/" + response.json()["opportunity_id"]
    ).json()
    assert opportunity["status"] == "considering" and opportunity["decisions"] == []
    assert opportunity["feedback"][0]["id"] == item["id"]
    assert (
        c.get("/api/v1/feedback?status=all&feedback_id=" + item["id"]).json()["items"]
        == triaged
    )
    assert (
        client("admin", "beta")
        .get("/api/v1/feedback?status=all&feedback_id=" + item["id"])
        .json()["items"]
        == []
    )


def test_decisions_authorization_validation_history_and_conflicts(triage_setup):
    store, ids, client, _ = triage_setup
    oid = seed_opportunity(store, principal(store, ids))
    path = f"/api/v1/opportunities/{oid}/decisions"
    payload = {
        "status": "planned",
        "expected_status": "considering",
        "note": "Validated demand; plan discovery.",
    }
    assert client("viewer").post(path, json=payload).status_code == 403
    assert client("admin", "beta").post(path, json=payload).status_code == 404
    c = client("editor")
    for bad in [
        dict(payload, status="confirmed"),
        dict(payload, note="x" * 4001),
        dict(payload, actor_id="forged"),
    ]:
        assert c.post(path, json=bad).status_code == 422
    result = c.post(path, json=payload)
    assert result.status_code == 200, result.text
    decision = result.json()["decisions"][0]
    assert decision["actor_id"] == ids["editor@example.com"]
    assert (
        decision["previous_status"] == "considering"
        and decision["new_status"] == "planned"
    )
    assert decision["note"] == payload["note"] and decision["created_at"]
    assert c.post(path, json=payload).status_code == 409
    previous = "planned"
    for status in [
        "in_progress",
        "shipped",
        "not_pursuing",
        "considering",
        "considering",
    ]:
        result = c.post(
            path,
            json={
                "status": status,
                "expected_status": previous,
                "note": "Explicit PM decision.",
            },
        )
        assert result.status_code == 200
        previous = status
    detail = client("viewer").get(f"/api/v1/opportunities/{oid}").json()
    assert len(detail["decisions"]) == 6 and not detail["can_edit"]
    viewer = principal(store, ids, "viewer")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with store.connection(viewer) as db:
            db.execute(
                "INSERT INTO opportunity_decisions(id,workspace_id,opportunity_id,actor_id,previous_status,new_status,note) VALUES(gen_random_uuid(),%s,%s,%s,'considering','planned','forged')",
                (viewer.tenant_id, oid, viewer.subject),
            )
    with store.connection(viewer) as db:
        assert (
            db.execute(
                "UPDATE opportunities SET status='planned' WHERE id=%s RETURNING id",
                (oid,),
            ).fetchone()
            is None
        )


def test_approval_failure_rolls_back_link_opportunity_and_status(
    triage_setup, monkeypatch
):
    store, ids, client, _ = triage_setup
    c = client("admin")
    p = principal(store, ids)
    item = make_request(c)
    run = approve(store, p, item)
    original = store._audit

    def fail(db, tenant, subject, action):
        if action == "feedback.opportunity_linked":
            raise ValueError("Injected transaction failure")
        return original(db, tenant, subject, action)

    monkeypatch.setattr(store, "_audit", fail)
    assert (
        c.post(f"/api/v1/feedback/{item['id']}/triage/{run['id']}/confirm").status_code
        == 409
    )
    assert c.get("/api/v1/feedback?status=new").json()["items"][0]["id"] == item["id"]
    assert c.get("/api/v1/opportunities").json()["items"] == []
    assert (
        c.get(f"/api/v1/feedback/{item['id']}/triage").json()["linked_opportunity"]
        is None
    )


def test_existing_approved_links_backfill_without_inventing_decisions(
    triage_setup, pg_store
):
    from app_core.migrate import migrate

    store, ids, client, _ = triage_setup
    c = client("admin")
    p = principal(store, ids)
    linked = make_request(c)
    unreviewed = make_request(c, title="Not approved")
    run = approve(store, p, linked)
    oid = store.confirm_triage(p, UUID(linked["id"]), run["id"])["opportunity_id"]
    # Reconstruct the previous schema in this disposable test database only.
    with psycopg.connect(pg_store[1]) as db:
        latest_schema = db.execute(
            "SELECT max(version) FROM app_core.schema_migrations"
        ).fetchone()[0]
        db.execute("DROP POLICY feedback_submitter_return ON app_core.feedback")
        db.execute("DROP TABLE app_core.opportunity_decisions")
        db.execute("DROP POLICY feedback_update ON app_core.feedback")
        db.execute("DROP POLICY opportunities_update ON app_core.opportunities")
        db.execute("ALTER TABLE app_core.feedback DROP COLUMN status")
        db.execute("ALTER TABLE app_core.opportunities DROP COLUMN status")
        db.execute("DELETE FROM app_core.schema_migrations WHERE version=8")
    assert migrate(pg_store[1]) == latest_schema
    assert migrate(pg_store[1]) == latest_schema
    assert [
        row["id"] for row in c.get("/api/v1/feedback?status=triaged").json()["items"]
    ] == [linked["id"]]
    assert [
        row["id"] for row in c.get("/api/v1/feedback?status=new").json()["items"]
    ] == [unreviewed["id"]]
    detail = c.get(f"/api/v1/opportunities/{oid}").json()
    assert detail["status"] == "considering" and detail["decisions"] == []


def test_status_changes_allow_missing_or_blank_note(triage_setup):
    store, ids, client, _ = triage_setup
    oid = seed_opportunity(store, principal(store, ids))
    path = f"/api/v1/opportunities/{oid}/decisions"
    for previous, status, extra in [
        ("considering", "planned", {}),
        ("planned", "in_progress", {"note": "   "}),
    ]:
        response = client("editor").post(
            path, json={"status": status, "expected_status": previous, **extra}
        )
        assert response.status_code == 200, response.text
        decision = response.json()["decisions"][0]
        assert decision["note"] == ""
        assert decision["previous_status"] == previous
        assert decision["new_status"] == status
        assert decision["actor_id"] == ids["editor@example.com"]
        assert decision["created_at"]
