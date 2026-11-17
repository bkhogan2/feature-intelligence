"""Real PostgreSQL queue, budget, recovery and authorization integration."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4
import pytest
from app_core.auto_triage import AutomationSettings, dispatch_once
from app_core.triage import TriageService
from test_feedback import feedback_setup as shared_feedback_setup
from test_triage import principal, make_request, output, fake_worker


@pytest.fixture
def setup(pg_store):
    return shared_feedback_setup.__wrapped__(pg_store)


def enable(store, p, limit="0.25", enabled=True):
    return store.save_auto_triage_config(
        p, AutomationSettings(enabled=enabled, daily_budget_usd=limit)
    )


def test_opt_in_capture_atomic_idempotency_and_roles(setup):
    store, ids, client, _ = setup
    c = client("admin")
    p = principal(store, ids)
    off = make_request(c)
    assert store.triage_state(p, UUID(off["id"]))["run"] is None
    assert (
        client("viewer")
        .put(
            "/api/v1/triage/automation",
            json={"enabled": True, "daily_budget_usd": 0.25},
        )
        .status_code
        == 403
    )
    assert (
        c.put(
            "/api/v1/triage/automation", json={"enabled": True, "daily_budget_usd": 0}
        ).status_code
        == 422
    )
    assert (
        c.put(
            "/api/v1/triage/automation",
            json={"enabled": True, "daily_budget_usd": 0.25},
        ).status_code
        == 200
    )
    key = uuid4()
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(
            pool.map(
                lambda _: store.create_feedback(
                    p, "Internal acceptance", "Testing duplicate submit.", key
                ),
                range(2),
            )
        )
    assert rows[0]["id"] == rows[1]["id"]
    state = store.triage_state(p, rows[0]["id"])
    assert state["run"]["status"] == "queued" and state["run"]["automatic"]
    assert state["linked_opportunity"] is None
    assert c.get("/api/v1/feedback?status=new").json()["items"][0]["id"] == str(
        rows[0]["id"]
    )
    assert (
        client("admin", "beta").get("/api/v1/triage/automation").json()["enabled"]
        is False
    )
    assert (
        client("admin", "beta")
        .get(f"/api/v1/feedback/{rows[0]['id']}/triage")
        .status_code
        == 404
    )
    with store.connection() as db:
        assert db.execute("SELECT * FROM auto_triage_settings").fetchall() == []
        assert db.execute("SELECT * FROM triage_runs").fetchall() == []
    with pytest.raises(ValueError):
        store.create_feedback(p, "Changed payload", "Testing duplicate submit.", key)
    enable(store, p, enabled=False)
    new = make_request(c, "Off again")
    assert store.triage_state(p, UUID(new["id"]))["run"] is None
    queued, _ = store.start_triage(p, rows[0]["id"], "test", "test", 120)
    assert queued["status"] == "queued" and "paused" in queued["error"]


def test_duplicate_claim_budget_and_restart_reconciliation(setup):
    store, ids, client, _ = setup
    p = principal(store, ids)
    enable(store, p, "0.05")
    first = store.create_feedback(p, "First", "Internal first")
    second = store.create_feedback(p, "Second", "Internal second")
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(
            pool.map(
                lambda _: store.start_triage(p, first["id"], "test", "test", 120),
                range(2),
            )
        )
    assert sum(created for _, created in claims) == 1
    assert claims[0][0]["id"] == claims[1][0]["id"]
    run = claims[0][0]
    pending, created = store.start_triage(p, second["id"], "test", "test", 120)
    assert (
        not created
        and pending["status"] == "queued"
        and "allocation" in pending["error"]
    )
    assert float(store.auto_triage_config(p)["reserved_today_usd"]) == 0.05
    # Simulate a process dying after dispatch: no automatic replay of uncertain provider work.
    with store.connection(p) as db:
        db.execute(
            "UPDATE triage_runs SET deadline_at=now()-interval '1 second' WHERE id=%s",
            (run["id"],),
        )
    assert store.triage_state(p, first["id"])["run"]["status"] == "failed"
    assert float(store.auto_triage_config(p)["reserved_today_usd"]) == 0.05
    # A fresh service can recover the durable pending second row after explicit allocation increase.
    enable(store, p, "0.10")
    recovered, created = store.start_triage(p, second["id"], "test", "test", 120)
    assert created and recovered["id"] == pending["id"]
    assert float(store.auto_triage_config(p)["reserved_today_usd"]) == 0.10
    store.finish_triage(
        p,
        recovered["id"],
        output({"id": str(second["id"]), "description": "Internal second"}),
        cost=0.08,
    )
    assert float(store.auto_triage_config(p)["reserved_today_usd"]) == 0.13


def test_durable_dispatch_uses_same_model_and_preserves_human_gate(setup, monkeypatch):
    store, ids, client, app = setup
    p = principal(store, ids)
    enable(store, p)
    item = make_request(
        client("admin"), "Internal acceptance check", "I need an explicit next action."
    )
    captured, writes = fake_worker(monkeypatch, output(item))

    async def exercise():
        service = TriageService(
            store,
            lambda request: (_ for _ in ()).throw(
                AssertionError("Browser session should not be needed")
            ),
        )
        await dispatch_once(service)
        await asyncio.gather(*list(service.tasks.values()))
        await service.close()

    asyncio.run(exercise())
    state = store.triage_state(p, UUID(item["id"]))
    assert state["run"]["status"] == "complete"
    assert state["run"]["result"]["outcome"] == "new_opportunity"
    assert state["linked_opportunity"] is None
    assert store.opportunities(p)["items"] == []
    assert (
        client("admin").get("/api/v1/feedback?status=new").json()["items"][0]["id"]
        == item["id"]
    )
    assert (
        writes[0]["task"] == "triage"
        and writes[0]["context"]["request"]["id"] == item["id"]
    )
    assert "DATABASE_URL" not in captured["env"]
    assert (
        client("viewer")
        .post(f"/api/v1/feedback/{item['id']}/triage/{state['run']['id']}/confirm")
        .status_code
        == 403
    )


def test_revoked_submitter_does_not_run_queued_work(setup, monkeypatch):
    store, ids, client, _ = setup
    admin = principal(store, ids)
    editor = principal(store, ids, "editor")
    enable(store, admin)
    item = store.create_feedback(
        editor, "Internal revoked test", "Do not analyze after access is revoked."
    )
    fake_worker(
        monkeypatch, output({"id": str(item["id"]), "description": item["description"]})
    )
    with store.connection() as db:
        db.execute(
            "UPDATE memberships SET status='disabled' WHERE workspace_id=%s AND user_id=%s",
            (editor.tenant_id, editor.subject),
        )

    async def exercise():
        service = TriageService(store, None)
        await dispatch_once(service)
        assert not service.tasks
        await service.close()

    asyncio.run(exercise())
    assert store.triage_state(admin, item["id"])["run"]["status"] == "failed"
