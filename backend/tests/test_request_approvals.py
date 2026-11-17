import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID
import pytest
from app_core.auto_triage import dispatch_approval
from app_core.request_links import RequestLinks, RequestStatus
from test_feedback import feedback_setup as shared_feedback_setup
from test_triage import make_request, principal, seed_opportunity, output


@pytest.fixture
def setup(pg_store):
    return shared_feedback_setup.__wrapped__(pg_store)


class Service:
    def __init__(self, store):
        self.store = store
        self.started = []

    def configured(self):
        return True

    async def start(self, p, request, feedback_id, approval_id=None):
        row, created = self.store.start_triage(
            p, feedback_id, "test", "triage-v1", 120, 0.05, approval_id
        )
        if created:
            self.started.append(row)
        return row


def decision_notices(client):
    return [
        item for item in client.get("/api/v1/updates?mine=true").json()["items"]
        if item["kind"] != "receipt"
    ]


def enqueue(c, item):
    response = c.post(
        f"/api/v1/feedback/{item['id']}/approval",
        json={"expected_status": item["status"]},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_durable_approval_manual_links_scope_and_retry(setup):
    store, ids, client, _ = setup
    c = client("admin")
    p = principal(store, ids)
    item = make_request(c)
    path = f"/api/v1/feedback/{item['id']}/approval"
    assert (
        client("viewer").post(path, json={"expected_status": "new"}).status_code == 403
    )
    assert client("admin", "beta").get(path).status_code == 404
    first = enqueue(c, item)
    assert enqueue(c, item)["id"] == first["id"]
    # No browser-side confirmation. Dispatcher reads durable intent.
    service = Service(store)
    asyncio.run(dispatch_approval(service, p))
    assert len(service.started) == 1
    # Manual links added while AI runs win, and multiple links remain intact.
    a, b = (
        seed_opportunity(store, p, "Manual A"),
        seed_opportunity(store, p, "Manual B"),
    )
    store.set_request_links(
        p, UUID(item["id"]), RequestLinks(opportunity_ids=[a, b], expected_ids=[])
    )
    asyncio.run(dispatch_approval(Service(store), p))
    assert c.get(path).json()["status"] == "complete"
    state = store.triage_state(p, UUID(item["id"]))
    assert {str(o["id"]) for o in state["linked_opportunities"]} == {a, b}
    assert enqueue(c, item)["status"] == "complete"


def test_serial_approvals_duplicate_guard_and_restart(setup):
    store, ids, client, _ = setup
    c = client("admin")
    p = principal(store, ids)
    a, b = make_request(c, "First"), make_request(c, "Second")
    enqueue(c, a)
    enqueue(c, b)
    service = Service(store)
    asyncio.run(dispatch_approval(service, p))
    asyncio.run(dispatch_approval(Service(store), p))
    assert len(service.started) == 1
    first = service.started[0]
    store.finish_triage(p, first["id"], output(a))
    # A fresh dispatcher (restart) completes the saved run without a browser.
    asyncio.run(dispatch_approval(Service(store), p))
    asyncio.run(dispatch_approval(service, p))
    assert len(service.started) == 2
    second = service.started[1]
    assert len(store.opportunities(p)["items"]) == 1
    suggestion = output(b)
    suggestion["proposed_name"] = " REQUEST  OWNERSHIP! "
    store.finish_triage(p, second["id"], suggestion)
    asyncio.run(dispatch_approval(Service(store), p))
    assert len(store.opportunities(p)["items"]) == 1
    links = [
        store.triage_state(p, UUID(x["id"]))["linked_opportunity"]["id"] for x in (a, b)
    ]
    assert links[0] == links[1]
    notices = decision_notices(c)
    assert {notice["feedback_id"] for notice in notices} == {a["id"], b["id"]}
    assert len(notices) == 2
    assert all("was approved" in notice["body"] for notice in notices)
    for x in (a, b):
        assert (
            c.get(f"/api/v1/feedback/{x['id']}/approval").json()["status"] == "complete"
        )


def test_rejection_cancels_pending_approval_and_failure_retry(setup):
    store, ids, client, _ = setup
    c = client("admin")
    p = principal(store, ids)
    item = make_request(c)
    enqueue(c, item)
    service = Service(store)
    asyncio.run(dispatch_approval(service, p))
    store.set_request_status(
        p, UUID(item["id"]), RequestStatus(status="rejected", expected_status="new")
    )
    store.finish_triage(p, service.started[0]["id"], output(item))
    asyncio.run(dispatch_approval(service, p))
    assert not store.opportunities(p)["items"]
    notices = decision_notices(c)
    assert [notice["body"] for notice in notices] == ["Your request was rejected."]
    store.set_request_status(
        p, UUID(item["id"]), RequestStatus(status="rejected", expected_status="rejected")
    )
    assert decision_notices(c) == notices
    item["status"] = "rejected"
    job = enqueue(c, item)
    asyncio.run(dispatch_approval(service, p))
    store.finish_triage(p, service.started[-1]["id"], error="Provider failed")
    asyncio.run(dispatch_approval(service, p))
    state = c.get(f"/api/v1/feedback/{item['id']}/approval").json()
    assert state["status"] == "failed" and "Provider failed" in state["error"]
    assert enqueue(c, item)["id"] != job["id"]


def test_concurrent_confirmations_do_not_create_duplicates(setup):
    store, ids, client, _ = setup
    c = client("admin")
    p = principal(store, ids)
    items = [make_request(c, "Concurrent A"), make_request(c, "Concurrent B")]
    runs = []
    for item in items:
        row, _ = store.start_triage(p, UUID(item["id"]), "test", "triage-v1", 120)
        store.finish_triage(p, row["id"], output(item))
        runs.append(row)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda pair: store.confirm_triage(
                    p, UUID(pair[0]["id"]), pair[1]["id"]
                ),
                zip(items, runs),
            )
        )
    assert results[0]["opportunity_id"] == results[1]["opportunity_id"]
    assert len(store.opportunities(p)["items"]) == 1


def test_unconfigured_ai_allows_manual_links_and_reports_unlinked_failure(setup):
    store, ids, client, _ = setup
    c, p = client("admin"), principal(store, ids)
    service = Service(store)
    service.configured = lambda: False
    item = make_request(c)
    enqueue(c, item)
    asyncio.run(dispatch_approval(service, p))
    state = store.approval_state(p, UUID(item["id"]))
    assert state["status"] == "failed"
    assert "not configured" in state["error"]
    target = seed_opportunity(store, p, "Manual")
    store.set_request_links(
        p, UUID(item["id"]), RequestLinks(opportunity_ids=[target], expected_ids=[])
    )
    enqueue(c, item)
    asyncio.run(dispatch_approval(service, p))
    assert store.approval_state(p, UUID(item["id"]))["status"] == "complete"
    assert service.started == []


def test_concurrent_dispatchers_claim_one_run(setup):
    store, ids, client, _ = setup
    c, p = client("admin"), principal(store, ids)
    item = make_request(c)
    enqueue(c, item)
    services = [Service(store), Service(store)]

    async def dispatch():
        await asyncio.gather(*(dispatch_approval(service, p) for service in services))

    asyncio.run(dispatch())
    assert sum(len(service.started) for service in services) == 1
    assert store.approval_state(p, UUID(item["id"]))["status"] == "running"
