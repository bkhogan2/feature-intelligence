"""Joint output grounding and transaction safeguards without live model calls."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app_core.priority_models import (
    BatchPriorityRequest,
    BatchPriorityDecision,
    validate_batch_suggestions,
)
from app_core.priority_store import PriorityStore
from app_core.batch_priority_store import BatchPriorityStore
from app_core.batch_priority import BatchPriorityService
from app_core.domain.models import WorkspaceRole
from test_priority import suggestion


def test_joint_output_exact_coverage_and_per_item_sources():
    a, b, fid = map(str, (uuid4(), uuid4(), uuid4()))
    evidence = {a: [dict(id=fid, description="Manual comparison")], b: []}
    first = dict(
        opportunity_id=a,
        suggestion=suggestion([dict(feedback_id=fid, quote="Manual comparison")]),
    )
    second = dict(opportunity_id=b, suggestion=suggestion())
    assert set(validate_batch_suggestions(dict(items=[first, second]), evidence)) == {
        a,
        b,
    }
    for items in [
        [first],
        [first, first],
        [first, dict(second, opportunity_id=str(uuid4()))],
        [first, dict(second, suggestion=first["suggestion"])],
    ]:
        with pytest.raises(ValueError):
            validate_batch_suggestions(dict(items=items), evidence)


def test_batch_bounds_and_inherited_budget():
    for ids in [[], [str(uuid4()) for _ in range(51)]]:
        with pytest.raises(ValidationError):
            BatchPriorityRequest(opportunity_ids=ids)
    service = BatchPriorityService(None, None)
    assert service.policy.max_budget_usd == 0.05
    assert service.policy.max_output_tokens == 32768
    assert service.policy.worker_env()["AGENT_MAX_BUDGET_USD"] == "0.05"


class FakeStore(BatchPriorityStore, PriorityStore):
    def __init__(self, rows):
        self.rows = {
            oid: {"effort": "PM estimate", "dependencies": "API", **row}
            for oid, row in rows.items()
        }
        self.writes = []
        self.audits = []

    @contextmanager
    def connection(self, p):
        writes = list(self.writes)
        audits = list(self.audits)
        try:
            yield self
        except Exception:
            self.writes = writes
            self.audits = audits
            raise

    def execute(self, sql, args):
        if sql.startswith("SELECT id FROM"):
            return SimpleNamespace(
                fetchall=lambda: [dict(id=oid) for oid in args[1] if oid in self.rows]
            )
        if sql.startswith("SELECT priority_revision"):
            return SimpleNamespace(fetchone=lambda: self.rows.get(args[0]))
        if sql.startswith("UPDATE opportunities"):
            self.writes.append(args)
        return SimpleNamespace(fetchone=lambda: None)

    def _audit(self, *args):
        self.audits.append(args)

    def opportunity(self, p, oid):
        return dict(id=str(oid))


def decision(oid, **kwargs):
    return BatchPriorityDecision(
        opportunity_id=oid,
        priority="high",
        rationale="Review compared workflow value",
        expected_revision=0,
        expected_evidence_revision=0,
        **kwargs,
    )


@pytest.mark.parametrize("stale", ["priority_revision", "evidence_revision"])
def test_batch_conflict_rolls_back_every_confirmation(stale):
    a, b = sorted([uuid4(), uuid4()])
    rows = {
        a: dict(priority_revision=0, evidence_revision=0, priority_analysis=None),
        b: dict(priority_revision=0, evidence_revision=0, priority_analysis=None),
    }
    rows[b][stale] = 1
    store = FakeStore(rows)
    p = SimpleNamespace(role=WorkspaceRole.EDITOR, tenant_id="alpha", subject="pm")
    with pytest.raises(ValueError):
        store.save_batch_priority(p, [decision(a), decision(b)])
    assert store.writes == [] and store.audits == []


def test_batch_missing_duplicate_and_viewer_never_write():
    oid = uuid4()
    store = FakeStore(
        {oid: dict(priority_revision=0, evidence_revision=0, priority_analysis=None)}
    )
    p = SimpleNamespace(role=WorkspaceRole.EDITOR, tenant_id="alpha", subject="pm")
    assert store.save_batch_priority(p, [decision(oid), decision(uuid4())]) is None
    with pytest.raises(ValueError):
        store.save_batch_priority(p, [decision(oid), decision(oid)])
    p.role = WorkspaceRole.VIEWER
    with pytest.raises(PermissionError):
        store.save_batch_priority(p, [decision(oid)])
    assert not store.writes


def test_batch_confirm_subset_audits_each_row():
    oid = uuid4()
    store = FakeStore(
        {oid: dict(priority_revision=0, evidence_revision=0, priority_analysis=None)}
    )
    p = SimpleNamespace(role=WorkspaceRole.EDITOR, tenant_id="alpha", subject="pm")
    assert store.save_batch_priority(p, [decision(oid)]) == {
        "items": [{"id": str(oid)}]
    }
    assert len(store.writes) == len(store.audits) == 1
    assert store.writes[0][2:4] == ("PM estimate", "API")


@pytest.mark.parametrize("invalid", [False, True])
def test_one_isolated_worker_compares_all_items_and_accounts_once(monkeypatch, invalid):
    import asyncio
    from test_triage import fake_worker

    ids = [str(uuid4()), str(uuid4())]
    results = {
        "items": [dict(opportunity_id=oid, suggestion=suggestion()) for oid in ids]
    }
    if invalid:
        results["items"].pop()
    captured, writes = fake_worker(
        monkeypatch,
        None,
        events=[dict(type="done", error=False, result=results, cost_usd=0.003)],
    )
    finishes = []

    class Store:
        def opportunity(self, p, oid):
            return dict(
                name=oid,
                problem="PM workflow",
                status="considering",
                effort="",
                dependencies="",
                feedback=[],
                priority_revision=0,
                evidence_revision=0,
            )

        def finish_priority(self, *args):
            finishes.append(args)

    service = BatchPriorityService(Store(), None)
    p = SimpleNamespace(subject="pm", tenant_id="alpha")

    async def current(*args):
        return p

    service.current = current
    row = {
        "id": str(uuid4()),
        "items": [
            dict(
                opportunity_id=oid,
                expected_revision=0,
                expected_evidence_revision=0,
                current_priority=None,
                analysis={"product_context": {"goals": "Reduce manual PM effort"}},
            )
            for oid in ids
        ],
    }
    asyncio.run(service.run_batch(p, object(), row))
    assert len(writes) == 1
    assert writes[0]["task"] == "priority_batch"
    assert [item["id"] for item in writes[0]["context"]["opportunities"]] == ids
    assert "DATABASE_URL" not in captured["env"]
    assert captured["env"]["AGENT_MAX_BUDGET_USD"] == "0.05"
    assert len(finishes) == 2
    assert [item[2]["cost_usd"] for item in finishes] == [0.003, 0]
    assert all((item[3] is None) == invalid for item in finishes)
