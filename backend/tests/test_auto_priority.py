"""Real PostgreSQL post-approval priority queue, shared budget and evidence races."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID
import pytest
from app_core.auto_triage import AutomationSettings
from app_core.auto_priority import dispatch_priority_once
from app_core.priority import PriorityService
from app_core.triage_models import TriageConfirmation
from test_feedback import feedback_setup as shared_feedback_setup
from test_triage import principal, seed_opportunity, make_request, output, fake_worker
from test_priority import suggestion


@pytest.fixture
def setup(pg_store):
    return shared_feedback_setup.__wrapped__(pg_store)


def enable(store, p, limit="0.25", priority=True, triage=False):
    return store.save_auto_triage_config(
        p,
        AutomationSettings(
            enabled=triage, priority_enabled=priority, daily_budget_usd=limit
        ),
    )


def approve(store, p, c, target=None, choice=None):
    item = make_request(c)
    run, _ = store.start_triage(p, UUID(item["id"]), "test", "test", 120)
    store.finish_triage(
        p,
        run["id"],
        output(item, "existing_opportunity" if target else "new_opportunity", target),
    )
    result = store.confirm_triage(p, UUID(item["id"]), run["id"], choice)
    return result["opportunity_id"], item, run


def test_approval_hook_opt_in_corrected_target_and_idempotency(setup):
    store, ids, client, _ = setup
    p = principal(store, ids)
    c = client("admin")
    off, _, _ = approve(store, p, c)
    assert store.opportunity(p, off)["priority_analysis"] is None
    enable(store, p)
    suggested = seed_opportunity(store, p, "AI target")
    corrected = seed_opportunity(store, p, "PM target")
    choice = TriageConfirmation(
        mode="existing", opportunity_id=corrected, reason="Actual chosen need."
    )
    oid, item, run = approve(store, p, c, suggested, choice)
    pending = store.opportunity(p, oid)["priority_analysis"]
    assert pending["status"] == "queued" and pending["automatic"]
    assert store.opportunity(p, suggested)["priority_analysis"] is None
    assert store.confirm_triage(p, UUID(item["id"]), run["id"], choice)[
        "opportunity_id"
    ] == UUID(corrected)
    assert store.opportunity(p, oid)["priority_analysis"]["id"] == pending["id"]
    assert len(store.queued_priority(p)) == 1
    assert (
        client("viewer")
        .put(
            "/api/v1/triage/automation",
            json={"enabled": False, "priority_enabled": True, "daily_budget_usd": 0.25},
        )
        .status_code
        == 403
    )
    assert (
        client("admin", "beta").get(f"/api/v1/opportunities/{oid}").status_code == 404
    )
    with store.connection() as db:
        assert db.execute("SELECT * FROM priority_jobs").fetchall() == []
    with store.connection(principal(store, ids, "viewer")) as db:
        assert (
            db.execute(
                "UPDATE priority_jobs SET status='failed' RETURNING id"
            ).fetchall()
            == []
        )


def test_coalescing_manual_race_stale_result_and_pm_fields_preserved(setup):
    store, ids, client, _ = setup
    p = principal(store, ids)
    c = client("admin")
    enable(store, p)
    oid, _, _ = approve(store, p, c)
    c.put(
        f"/api/v1/opportunities/{oid}/priority",
        json={
            "priority": "medium",
            "rationale": "PM review",
            "effort": "PM estimate",
            "dependencies": "PM dependencies",
            "expected_revision": 0,
        },
    )
    before = store.opportunity(p, oid)
    queued = before["priority_analysis"]["id"]
    approve(store, p, c, str(oid))
    assert store.opportunity(p, oid)["priority_analysis"]["id"] == queued
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(
            pool.map(lambda _: store.start_priority(p, oid, "test", 120), range(2))
        )
    assert sum(created for _, created in claims) == 1
    run = claims[0][0]
    assert run["based_on_evidence_revision"] == 2
    approve(store, p, c, str(oid))
    next_id = store.opportunity(p, oid)["priority_analysis"]["id"]
    assert next_id != run["id"]
    store.finish_priority(p, oid, {**run, "cost_usd": 0.001}, suggestion())
    assert store.opportunity(p, oid)["priority_analysis"]["id"] == next_id
    next_run, created = store.start_priority(p, oid, "test", 120)
    assert created and next_run["based_on_evidence_revision"] == 3
    store.finish_priority(p, oid, next_run, suggestion())
    after = store.opportunity(p, oid)
    for field in (
        "priority",
        "priority_rationale",
        "effort",
        "dependencies",
        "status",
        "priority_revision",
    ):
        assert after[field] == before[field]
    assert after["priority_analysis"]["status"] == "complete"
    assert len(after["feedback"]) == 3


def test_shared_allocation_pause_expiry_and_no_silent_retry(setup):
    store, ids, client, _ = setup
    p = principal(store, ids)
    c = client("admin")
    enable(store, p, "0.05", triage=True)
    item = make_request(c)
    tr, created = store.start_triage(p, UUID(item["id"]), "test", "test", 120)
    assert created and tr["automatic"]
    store.finish_triage(p, tr["id"], output(item), cost=0.001)
    oid = store.confirm_triage(p, UUID(item["id"]), tr["id"])["opportunity_id"]
    queued, created = store.start_priority(p, oid, "test", 120)
    assert not created and "allocation" in queued["error"]
    enable(store, p, "0.10", priority=False)
    assert "paused" in store.start_priority(p, oid, "test", 120)[0]["error"]
    enable(store, p, "0.10")
    run, created = store.start_priority(p, oid, "test", 120)
    assert created
    with store.connection(p) as db:
        db.execute(
            "UPDATE priority_jobs SET deadline_at=now()-interval '1 second' WHERE id=%s",
            (run["id"],),
        )
    assert store.queued_priority(p) == []
    assert store.opportunity(p, oid)["priority_analysis"]["status"] == "failed"
    store.finish_priority(p, oid, {**run, "cost_usd": 0.08}, suggestion())
    assert store.opportunity(p, oid)["priority_analysis"]["status"] == "failed"
    assert float(store.auto_triage_config(p)["reserved_today_usd"]) == pytest.approx(
        0.13
    )


def test_restart_dispatch_uses_combined_evidence_and_never_accepts(setup, monkeypatch):
    store, ids, client, _ = setup
    p = principal(store, ids)
    c = client("admin")
    enable(store, p)
    oid, item, _ = approve(store, p, c)
    _, second, _ = approve(store, p, c, str(oid))
    expected = suggestion([{"feedback_id": item["id"], "quote": item["description"]}])
    _, writes = fake_worker(
        monkeypatch,
        None,
        events=[
            {"type": "done", "error": False, "result": expected, "cost_usd": 0.002}
        ],
    )

    async def run():
        service = PriorityService(store, lambda request: p)
        await dispatch_priority_once(service)
        await asyncio.gather(*service.tasks.values())
        await service.close()

    asyncio.run(run())
    detail = store.opportunity(p, oid)
    assert detail["priority_analysis"]["status"] == "complete"
    assert detail["priority"] is None and detail["status"] == "considering"
    assert {f["id"] for f in writes[0]["context"]["feedback"]} == {
        item["id"],
        second["id"],
    }
    assert len(writes) == 1


def test_changed_evidence_rejects_acceptance_when_automation_off(setup):
    store, ids, client, _ = setup
    p = principal(store, ids)
    c = client("admin")
    oid, _, _ = approve(store, p, c)
    run, _ = store.start_priority(p, oid, "test", 120)
    store.finish_priority(p, oid, run, suggestion())
    approve(store, p, c, str(oid))
    response = c.put(
        f"/api/v1/opportunities/{oid}/priority",
        json={
            "priority": "high",
            "rationale": suggestion()["rationale"],
            "expected_revision": 0,
            "accepted_analysis_id": run["id"],
        },
    )
    assert response.status_code == 409


def test_revoked_approver_queue_fails_without_provider_call(setup, monkeypatch):
    store, ids, client, _ = setup
    admin = principal(store, ids)
    editor = principal(store, ids, "editor")
    enable(store, admin)
    oid, _, _ = approve(store, editor, client("editor"))
    _, writes = fake_worker(
        monkeypatch,
        None,
        events=[
            {"type": "done", "error": False, "result": suggestion(), "cost_usd": 0.002}
        ],
    )
    with store.connection() as db:
        db.execute(
            "UPDATE memberships SET status='disabled' WHERE workspace_id=%s AND user_id=%s",
            (editor.tenant_id, editor.subject),
        )

    async def run():
        service = PriorityService(store, None)
        await dispatch_priority_once(service)
        assert not service.tasks
        await service.close()

    asyncio.run(run())
    assert not writes
    assert store.opportunity(admin, oid)["priority_analysis"]["status"] == "failed"
