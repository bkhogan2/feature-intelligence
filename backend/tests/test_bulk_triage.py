"""Atomic human batch approvals against real PostgreSQL; no model calls."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from app_core.triage_models import TriageBatchConfirmation, TriageConfirmation
from test_triage import make_request, output, principal, seed_opportunity
from test_feedback import feedback_setup as shared_feedback_setup
from test_auto_priority import enable

PATH = "/api/v1/feedback/triage/confirm-batch"


@pytest.fixture
def setup(pg_store):
    return shared_feedback_setup.__wrapped__(pg_store)


def suggestion(store, p, c, outcome="new_opportunity", target=None):
    item = make_request(c)
    run, _ = store.start_triage(p, UUID(item["id"]), "test", "test", 120)
    store.finish_triage(p, run["id"], output(item, outcome, target))
    return {"feedback_id": item["id"], "run_id": str(run["id"])}


def test_batch_model_bounds_unique_requests_and_accept_only():
    item = {"feedback_id": str(uuid4()), "run_id": str(uuid4())}
    assert len(TriageBatchConfirmation(items=[item]).items) == 1
    for items in [
        [],
        [item] * 51,
        [item, item],
        [item, {**item, "run_id": str(uuid4())}],
        [{**item, "mode": "existing"}],
    ]:
        with pytest.raises(ValidationError):
            TriageBatchConfirmation(items=items)
    assert (
        len(
            TriageBatchConfirmation(
                items=[{"feedback_id": uuid4(), "run_id": uuid4()} for _ in range(50)]
            ).items
        )
        == 50
    )


def test_batch_mixed_targets_idempotence_audit_and_priority(setup):
    store, ids, client, _ = setup
    p, c = principal(store, ids), client("editor")
    enable(store, p)
    target = seed_opportunity(store, p, "Separate existing problem")
    items = [
        suggestion(store, p, c),
        suggestion(store, p, c, "existing_opportunity", target),
    ]
    response = c.post(PATH, json={"items": items})
    assert response.status_code == 200, response.text
    assert response.json()["items"][1]["opportunity_id"] == target
    with store.connection(p) as db:
        before = db.execute("SELECT count(*) AS n FROM audit").fetchone()["n"]
    assert c.post(PATH, json={"items": items}).json() == response.json()
    assert len(store.opportunities(p)["items"]) == 2
    assert len(store.queued_priority(p)) == 2
    with store.connection(p) as db:
        assert db.execute("SELECT count(*) AS n FROM audit").fetchone()["n"] == before
        assert (
            db.execute(
                "SELECT count(*) AS n FROM feedback WHERE status='triaged'"
            ).fetchone()["n"]
            == 2
        )
        assert all(
            row["confirmation"]["choice"] == {"mode": "accept"}
            for row in db.execute(
                "SELECT confirmation FROM feedback_opportunity_links"
            ).fetchall()
        )


@pytest.mark.parametrize(
    "fault",
    [
        "unclear",
        "failed",
        "stale",
        "unknown",
        "foreign",
        "archived",
        "archived_target",
        "corrected",
    ],
)
def test_batch_rolls_back_every_write_on_invalid_member(setup, fault):
    store, ids, client, _ = setup
    p, c = principal(store, ids), client("admin")
    enable(store, p)
    good = suggestion(store, p, c)
    bad = suggestion(
        store, p, c, "insufficient_context" if fault == "unclear" else "new_opportunity"
    )
    if fault == "failed":
        with store.connection(p) as db:
            db.execute(
                "UPDATE triage_runs SET status='failed',result=NULL WHERE id=%s",
                (bad["run_id"],),
            )
    elif fault == "stale":
        store.start_triage(p, UUID(bad["feedback_id"]), "test", "test", 120)
    elif fault == "unknown":
        bad["run_id"] = str(uuid4())
    elif fault == "foreign":
        bad = suggestion(
            store, principal(store, ids, workspace="beta"), client("admin", "beta")
        )
    elif fault == "archived":
        assert (
            c.patch(
                "/api/v1/feedback/bulk",
                json={"ids": [bad["feedback_id"]], "archived": True},
            ).status_code
            == 200
        )
    elif fault == "archived_target":
        target = seed_opportunity(store, p)
        bad = suggestion(store, p, c, "existing_opportunity", target)
        assert (
            c.patch(
                "/api/v1/opportunities/bulk", json={"ids": [target], "archived": True}
            ).status_code
            == 200
        )
    elif fault == "corrected":
        store.confirm_triage(
            p,
            UUID(bad["feedback_id"]),
            UUID(bad["run_id"]),
            TriageConfirmation(
                mode="edit_new",
                name="Human name",
                problem="Human problem",
                reason="Correction",
            ),
        )
    with store.connection(p) as db:
        before = {
            table: db.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
            for table in (
                "opportunities",
                "feedback_opportunity_links",
                "priority_jobs",
                "audit",
            )
        }
    response = c.post(PATH, json={"items": [good, bad]})
    assert response.status_code == (404 if fault in {"unknown", "foreign"} else 409), (
        response.text
    )
    assert (
        store.triage_state(p, UUID(good["feedback_id"]))["linked_opportunity"] is None
    )
    with store.connection(p) as db:
        for table, count in before.items():
            assert (
                db.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
                == count
            )


def test_batch_roles_tenant_csrf_and_duplicates(setup):
    store, ids, client, app = setup
    p, c = principal(store, ids), client("admin")
    item = suggestion(store, p, c)
    body = {"items": [item]}
    assert client("viewer").post(PATH, json=body).status_code == 403
    assert client("admin", "beta").post(PATH, json=body).status_code == 404
    assert client("outsider").post(PATH, json=body).status_code == 404
    assert c.post(PATH, json=body, headers={"X-App-Request": ""}).status_code == 403
    assert (
        c.post(PATH, json=body, headers={"Origin": "https://evil.invalid"}).status_code
        == 403
    )
    assert c.post(PATH, json={"items": [item, item]}).status_code == 422
    assert (
        store.triage_state(p, UUID(item["feedback_id"]))["linked_opportunity"] is None
    )


def test_concurrent_reversed_batches_reuse_links_without_duplicates(setup):
    store, ids, client, _ = setup
    p, c = principal(store, ids), client("admin")
    items = [suggestion(store, p, c), suggestion(store, p, c)]

    def confirm(sequence):
        return store.confirm_triage_batch(p, TriageBatchConfirmation(items=sequence))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(confirm, items),
            pool.submit(confirm, list(reversed(items))),
        ]
        results = [f.result(timeout=10) for f in futures]
    assert results[0]["items"] == list(reversed(results[1]["items"]))
    assert len(store.opportunities(p)["items"]) == 1


def test_archived_target_after_approval_keeps_retry_idempotent(setup):
    store, ids, client, _ = setup
    p, c = principal(store, ids), client("admin")
    target = seed_opportunity(store, p)
    body = {"items": [suggestion(store, p, c, "existing_opportunity", target)]}
    first = c.post(PATH, json=body)
    assert first.status_code == 200
    assert (
        c.patch(
            "/api/v1/opportunities/bulk", json={"ids": [target], "archived": True}
        ).status_code
        == 200
    )
    assert c.post(PATH, json=body).json() == first.json()


def test_archive_commits_before_waiting_approval_and_is_not_revived(setup):
    from threading import Event

    store, ids, client, _ = setup
    p, c = principal(store, ids), client("admin")
    item = suggestion(store, p, c)
    started = Event()

    def confirm():
        started.set()
        return store.confirm_triage_batch(p, TriageBatchConfirmation(items=[item]))

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.connection(p) as db:
            db.execute(
                "UPDATE feedback SET archived_from_status=status,status='archived' WHERE id=%s",
                (item["feedback_id"],),
            )
            future = pool.submit(confirm)
            assert started.wait(timeout=5)
        with pytest.raises(ValueError, match="Restore archived"):
            future.result(timeout=10)
    state = store.triage_state(p, UUID(item["feedback_id"]))
    assert state["linked_opportunity"] is None
    with store.connection(p) as db:
        assert (
            db.execute(
                "SELECT status FROM feedback WHERE id=%s", (item["feedback_id"],)
            ).fetchone()["status"]
            == "archived"
        )
