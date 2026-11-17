from uuid import uuid4

import pytest

from test_feedback import feedback_setup as shared_feedback_setup
from test_triage import principal, seed_opportunity


@pytest.fixture
def setup(pg_store):
    return shared_feedback_setup.__wrapped__(pg_store)


def submit(client, title="Export reports"):
    result = client.post(
        "/api/v1/feedback",
        json={"title": title, "description": "I need usable reports."},
    )
    assert result.status_code == 201, result.text
    return result.json()


def test_draft_and_publish_reviewer_approved_update(setup, monkeypatch):
    store, ids, client, app = setup
    admin, editor, viewer = (client(role) for role in ("admin", "editor", "viewer"))
    beta = client("admin", "beta")
    request = submit(editor)
    other = submit(admin, "Schedule reports")
    opp = seed_opportunity(store, principal(store, ids))
    for item in (request, other):
        result = admin.put(
            f"/api/v1/feedback/{item['id']}/opportunities",
            json={"opportunity_ids": [opp], "expected_ids": [], "approve": True},
        )
        assert result.status_code == 200, result.text

    from app_core import submitter_updates

    async def fake_draft(mode, model, context, policy):
        assert mode == "submitter_update"
        assert context["status"] == "considering"
        return model(body="We're reviewing how exports could work.")

    monkeypatch.setattr(submitter_updates, "structured_draft", fake_draft)
    monkeypatch.setattr(app.state.triage_service, "configured", lambda: True)
    url = f"/api/v1/opportunities/{opp}/updates"
    assert viewer.post(f"{url}/draft").status_code == 403
    draft = admin.post(f"{url}/draft")
    assert draft.status_code == 200, draft.text
    assert "reviewing" in draft.json()["body"]
    before = admin.get("/api/v1/updates").json()["items"]
    assert [item["kind"] for item in before].count("receipt") == 2
    assert sum("was approved" in item["body"] for item in before) == 2
    payload = {
        "id": str(uuid4()),
        "body": "Thanks. We’re reviewing exports.",
        "expected_status": "considering",
        "expected_requests": [request["id"], other["id"]],
    }
    assert (
        admin.post(
            url, json={**payload, "expected_requests": [request["id"]]}
        ).status_code
        == 409
    )
    assert (
        admin.post(url, json={**payload, "expected_status": "shipped"}).status_code
        == 409
    )
    assert viewer.post(url, json=payload).status_code == 403
    published = admin.post(url, json=payload)
    assert published.status_code == 200, published.text
    assert admin.post(url, json=payload).json() == {"request_count": 2}
    assert len(admin.get("/api/v1/updates").json()["items"]) == 6
    own = editor.get("/api/v1/updates?mine=true").json()["items"]
    assert len(own) == 3 and all(item["feedback_id"] == request["id"] for item in own)
    assert own[0]["body"] == payload["body"]
    assert viewer.get("/api/v1/updates").json()["items"] == []
    assert beta.get("/api/v1/updates").json()["items"] == []


def test_clarification_is_private_and_reply_returns_request_to_review(setup):
    store, ids, client, _ = setup
    admin, editor, viewer = (client(role) for role in ("admin", "editor", "viewer"))
    request = submit(editor)
    rid = request["id"]
    url = f"/api/v1/feedback/{rid}/updates"
    question = {
        "id": str(uuid4()),
        "body": "Which report is missing information?",
        "kind": "clarification",
        "expected_status": "new",
    }
    asked = admin.post(url, json=question)
    assert asked.status_code == 200, asked.text
    entry = admin.get(f"/api/v1/updates?feedback_id={rid}").json()["items"][0]
    assert entry["request_status"] == "needs_clarification"
    reply_url = f"/api/v1/updates/{entry['id']}/reply"
    assert (
        viewer.post(reply_url, json={"body": "An impersonated reply"}).status_code
        == 404
    )
    assert (
        admin.post(
            reply_url, json={"body": "A reviewer cannot impersonate"}
        ).status_code
        == 404
    )
    assert (
        admin.post(
            f"/api/v1/feedback/{rid}/approval",
            json={"expected_status": "needs_clarification"},
        ).status_code
        == 409
    )
    assert (
        admin.post(
            url,
            json={
                **question,
                "id": str(uuid4()),
                "expected_status": "needs_clarification",
            },
        ).status_code
        == 409
    )

    member = next(
        row
        for row in admin.get("/api/v1/workspace/members").json()
        if row["email"] == "editor@example.com"
    )
    downgraded = admin.patch(
        f"/api/v1/workspace/members/{member['membership_id']}", json={"role": "viewer"}
    )
    assert downgraded.status_code == 200, downgraded.text
    mine = editor.get("/api/v1/updates").json()["items"]
    assert mine[0]["is_recipient"] and mine[0]["id"] == entry["id"]
    answer = {"body": "The weekly CSV omits the date."}
    sent = editor.post(reply_url, json=answer)
    assert sent.status_code == 200, sent.text
    assert editor.post(reply_url, json=answer).status_code == 200
    assert editor.post(reply_url, json={"body": "Different reply"}).status_code == 409
    current = admin.get(f"/api/v1/feedback?feedback_id={rid}&status=new").json()[
        "items"
    ]
    assert len(current) == 1 and current[0]["description"] == request["description"]
    visible = admin.get(f"/api/v1/updates?feedback_id={rid}").json()["items"][0]
    assert visible["reply"] == answer["body"]
    assert store.triage_clarifications(principal(store, ids), rid) == [
        {"question": question["body"], "answer": answer["body"]}
    ]


def test_outcome_requires_shipment_evidence_and_current_revision(setup):
    store, ids, client, _ = setup
    admin, viewer = (client(role) for role in ("admin", "viewer"))
    p = principal(store, ids)
    opp = seed_opportunity(store, p)
    url = f"/api/v1/opportunities/{opp}/outcome"
    payload = {
        "status": "improved",
        "evidence": "Export time fell below a minute.",
        "expected_revision": 0,
    }
    assert admin.put(url, json=payload).status_code == 409
    with store.connection(p) as db:
        db.execute("UPDATE opportunities SET status='shipped' WHERE id=%s", (opp,))
    assert viewer.put(url, json=payload).status_code == 403
    assert admin.put(url, json={**payload, "evidence": ""}).status_code == 422
    result = admin.put(url, json=payload)
    assert result.status_code == 200, result.text
    assert admin.put(url, json=payload).status_code == 409
    detail = viewer.get(f"/api/v1/opportunities/{opp}").json()
    assert detail["outcome_status"] == "improved"
    assert detail["outcome_evidence"] == payload["evidence"]
    assert detail["outcome_revision"] == 1



def test_supporter_notifications_and_independent_read_state(setup):
    store, ids, client, _ = setup
    admin, editor, viewer = (client(role) for role in ("admin", "editor", "viewer"))
    request = submit(editor)
    rid = request["id"]
    support = viewer.post(f"/api/v1/feedback/{rid}/support")
    assert support.status_code == 200, support.text
    payload = {"id": str(uuid4()), "body": "Export work is planned.", "expected_status": "new"}
    result = admin.post(f"/api/v1/feedback/{rid}/updates", json=payload)
    assert result.status_code == 200, result.text
    # Publication retries must not duplicate deliveries.
    assert admin.post(f"/api/v1/feedback/{rid}/updates", json=payload).status_code == 200
    own = editor.get("/api/v1/updates?mine=true").json()["items"]
    supported = viewer.get("/api/v1/updates?mine=true").json()["items"]
    assert len(own) == 2 and len(supported) == 1
    message = supported[0]["id"]
    assert viewer.get("/api/v1/updates/unread").json()["count"] == 1
    assert viewer.post(f"/api/v1/updates/{message}/read").status_code == 200
    assert viewer.post(f"/api/v1/updates/{message}/read").status_code == 200
    assert viewer.get("/api/v1/updates/unread").json()["count"] == 0
    assert editor.get("/api/v1/updates/unread").json()["count"] == 2
    assert admin.post(f"/api/v1/updates/{message}/read").status_code == 404
    assert client("admin", "beta").get("/api/v1/updates?mine=true").json()["items"] == []
    # Unliking stops future notifications but preserves previously delivered updates.
    assert viewer.delete(f"/api/v1/feedback/{rid}/support").status_code == 200
    assert admin.post(f"/api/v1/feedback/{rid}/updates", json={**payload,"id":str(uuid4())}).status_code == 200
    assert len(viewer.get("/api/v1/updates?mine=true").json()["items"]) == 1


def test_bulk_notification_archive_restore_and_recipient_isolation(setup):
    _, _, client, _ = setup
    admin, editor, viewer = (client(role) for role in ("admin", "editor", "viewer"))
    request = submit(editor)
    published = admin.post(
        f"/api/v1/feedback/{request['id']}/updates",
        json={"id": str(uuid4()), "body": "We are reviewing this request.",
              "kind": "update", "expected_status": "new"},
    )
    assert published.status_code == 200, published.text
    message = editor.get("/api/v1/updates?mine=true").json()["items"][0]
    payload = {"ids": [message["id"]], "action": "archive"}
    assert viewer.post("/api/v1/updates/bulk", json=payload).status_code == 200
    assert editor.get("/api/v1/updates/unread").json()["count"] == 2
    assert editor.post("/api/v1/updates/bulk", json=payload).status_code == 200
    assert editor.get("/api/v1/updates/unread").json()["count"] == 1
    archived = editor.get("/api/v1/updates?mine=true").json()["items"][0]
    assert archived["archived_at"] is not None
    assert archived["body"] == message["body"]
    for action, count in [("restore", 2), ("read", 1), ("unread", 2)]:
        result = editor.post("/api/v1/updates/bulk", json={**payload, "action": action})
        assert result.status_code == 200, result.text
        assert editor.get("/api/v1/updates/unread").json()["count"] == count
    assert editor.get("/api/v1/updates?mine=true").json()["items"][0]["archived_at"] is None

def test_submission_receipt_is_private_and_idempotent(setup):
    _, _, client, _ = setup
    editor, admin = client("editor"), client("admin")
    payload = {
        "title": "Export filtered requests",
        "description": "We need to share a filtered list.",
        "submission_key": str(uuid4()),
    }
    first = editor.post("/api/v1/feedback", json=payload)
    retry = editor.post("/api/v1/feedback", json=payload)
    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    assert editor.post("/api/v1/feedback", json={**payload, "title": "Changed"}).status_code == 409
    items = editor.get("/api/v1/updates?mine=true").json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "receipt" and items[0]["feedback_id"] == first.json()["id"]
    assert items[0]["read_at"] is None
    assert admin.get("/api/v1/updates?mine=true").json()["items"] == []
