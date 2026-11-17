"""Transactional human corrections, using real PostgreSQL and no model calls."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID
import pytest
from app_core.triage_models import TriageConfirmation
from test_feedback import feedback_setup as shared_feedback_setup
from test_triage import make_request, principal, seed_opportunity, output


@pytest.fixture
def setup(pg_store):
    return shared_feedback_setup.__wrapped__(pg_store)


def completed(store, p, item, outcome="new_opportunity", target=None):
    run, _ = store.start_triage(p, UUID(item["id"]), "test", "test", 120)
    result = output(item, outcome, target)
    store.finish_triage(p, run["id"], result=result)
    return run, result


def test_existing_correction_preserves_ai_and_records_actor(setup):
    store, ids, client, _ = setup
    c = client("admin")
    p = principal(store, ids)
    suggested = seed_opportunity(store, p, "Suggested")
    chosen = seed_opportunity(store, p, "Chosen")
    item = make_request(c)
    run, original = completed(store, p, item, "existing_opportunity", suggested)
    url = f"/api/v1/feedback/{item['id']}/triage/{run['id']}/confirm"
    choice = {
        "mode": "existing",
        "opportunity_id": chosen,
        "reason": "Distinct need fits the chosen problem.",
    }
    assert client("viewer").post(url, json=choice).status_code == 403
    assert c.post(url, json=choice).json()["opportunity_id"] == chosen
    assert c.post(url, json=choice).json()["opportunity_id"] == chosen
    assert c.post(url).status_code == 409
    assert c.post(url, json={**choice, "opportunity_id": suggested}).status_code == 409
    state = c.get(f"/api/v1/feedback/{item['id']}/triage").json()
    assert state["run"]["result"] == original
    link = state["linked_opportunity"]
    assert link["confirmation"]["choice"] == choice
    assert link["linked_by"] == p.subject and link["linked_at"]
    assert (
        c.get("/api/v1/feedback?status=triaged").json()["items"][0]["description"]
        == item["description"]
    )
    assert client("admin", "beta").post(url, json=choice).status_code == 404


def test_edited_new_races_are_atomic_and_idempotent(setup):
    store, ids, client, _ = setup
    p = principal(store, ids)
    item = make_request(client("admin"))
    run, original = completed(store, p, item)
    choice = TriageConfirmation(
        mode="edit_new",
        name="Reviewed title",
        problem="Reviewed problem.",
        reason="Use precise scope.",
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(
            pool.map(
                lambda _: store.confirm_triage(p, UUID(item["id"]), run["id"], choice),
                range(2),
            )
        )
    assert replies[0] == replies[1]
    assert len(store.opportunities(p)["items"]) == 1
    detail = store.opportunity(p, replies[0]["opportunity_id"])
    assert (
        detail["name"] == "Reviewed title" and detail["problem"] == "Reviewed problem."
    )
    assert detail["analysis"]["result"] == original
    assert (
        store.triage_state(p, UUID(item["id"]))["linked_opportunity"]["confirmation"][
            "choice"
        ]["mode"]
        == "edit_new"
    )


def test_cross_workspace_stale_and_insufficient_context_cannot_confirm(setup):
    store, ids, client, _ = setup
    c = client("admin")
    p = principal(store, ids)
    other = seed_opportunity(store, principal(store, ids, workspace="beta"))
    item = make_request(c)
    run, _ = completed(store, p, item)
    url = f"/api/v1/feedback/{item['id']}/triage/{run['id']}/confirm"
    correction = {
        "mode": "existing",
        "opportunity_id": other,
        "reason": "Test wrong workspace.",
    }
    assert c.post(url, json=correction).status_code == 409
    assert store.triage_state(p, UUID(item["id"]))["linked_opportunity"] is None
    assert store.opportunities(p)["items"] == []
    next_run, _ = completed(store, p, item, "insufficient_context")
    assert c.post(url).status_code == 409
    target = seed_opportunity(store, p)
    correction["opportunity_id"] = target
    assert (
        c.post(
            f"/api/v1/feedback/{item['id']}/triage/{next_run['id']}/confirm",
            json=correction,
        ).status_code
        == 409
    )
    assert c.get("/api/v1/feedback?status=new").json()["items"][0]["id"] == item["id"]
    assert (
        client("viewer").get("/api/v1/opportunities?search=Request").status_code == 200
    )
    with store.connection() as db:
        assert db.execute("SELECT * FROM feedback_opportunity_links").fetchall() == []


def test_validation_and_accept_path(setup):
    store, ids, client, _ = setup
    c = client("admin")
    p = principal(store, ids)
    item = make_request(c)
    run, _ = completed(store, p, item)
    url = f"/api/v1/feedback/{item['id']}/triage/{run['id']}/confirm"
    for invalid in (
        {"mode": "existing"},
        {"mode": "edit_new", "name": " ", "problem": "ok", "reason": "why"},
        {"mode": "accept", "reason": "unexpected"},
        {"mode": "edit_new", "name": "ok", "problem": "ok", "reason": " "},
    ):
        assert c.post(url, json=invalid).status_code == 422
    assert c.post(url).status_code == 200
    assert c.post(url).status_code == 200
    assert len(store.opportunities(p)["items"]) == 1
    assert store.triage_state(p, UUID(item["id"]))["linked_opportunity"][
        "confirmation"
    ]["choice"] == {"mode": "accept"}


def test_conflicting_choices_race_only_one_wins(setup):
    store, ids, client, _ = setup
    p = principal(store, ids)
    item = make_request(client("admin"))
    run, _ = completed(store, p, item)
    targets = [
        seed_opportunity(store, p, "First target"),
        seed_opportunity(store, p, "Second target"),
    ]

    def confirm(target):
        try:
            return store.confirm_triage(
                p,
                UUID(item["id"]),
                run["id"],
                TriageConfirmation(
                    mode="existing", opportunity_id=target, reason="Reviewed target."
                ),
            )
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(confirm, targets))
    assert sum(reply is not None for reply in replies) == 1
    assert len(store.opportunities(p)["items"]) == 2
    with store.connection(p) as db:
        assert (
            db.execute(
                "SELECT count(*) AS n FROM feedback_opportunity_links"
            ).fetchone()["n"]
            == 1
        )
