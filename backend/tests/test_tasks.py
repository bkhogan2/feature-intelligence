from uuid import uuid4

import pytest

from test_feedback import feedback_setup as shared_feedback_setup
from test_triage import principal, seed_opportunity


@pytest.fixture
def setup(pg_store):
    return shared_feedback_setup.__wrapped__(pg_store)


def test_task_delivery_flow_and_workspace_scope(setup):
    store, ids, client, _ = setup
    admin = client("admin")
    editor = client("editor")
    viewer = client("viewer")
    beta = client("admin", "beta")
    opportunity = seed_opportunity(store, principal(store, ids))
    another = seed_opportunity(store, principal(store, ids), "Different opportunity")
    payload = {
        "id": str(uuid4()),
        "opportunity_id": opportunity,
        "title": "Add the Restore button",
        "assignee_id": ids["viewer@example.com"],
    }

    assert viewer.post("/api/v1/tasks", json=payload).status_code == 403
    assert beta.post("/api/v1/tasks", json=payload).status_code == 404
    assert (
        editor.post(
            "/api/v1/tasks",
            json={**payload, "assignee_id": ids["outsider@example.com"]},
        ).status_code
        == 422
    )
    assert editor.get("/api/v1/tasks/assignees").status_code == 200
    created = editor.post("/api/v1/tasks", json=payload)
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "backlog"
    assert editor.post("/api/v1/tasks", json=payload).json() == task
    path = f"/api/v1/tasks/{task['id']}"
    assert viewer.get(path).json() == task
    assert beta.get(path).status_code == 404
    assert viewer.get(f"/api/v1/tasks?opportunity_id={opportunity}").json()[
        "items"
    ] == [task]
    assert viewer.get(f"/api/v1/tasks?opportunity_id={another}").json()["items"] == []

    for lane in ("todo", "in_progress", "blocked", "done"):
        patch = {"status": lane, "expected_revision": task["revision"]}
        assert viewer.patch(path, json=patch).status_code == 403
        result = editor.patch(path, json=patch)
        assert result.status_code == 200, result.text
        task = result.json()
        assert task["status"] == lane
        assert admin.get(path).json()["status"] == lane
        assert editor.patch(path, json=patch).status_code == 409
    assert (
        admin.get(f"/api/v1/opportunities/{opportunity}").json()["status"]
        == "considering"
    )

    description = "## Implementation\n\nKeep linked evidence in place."
    saved = editor.patch(
        path, json={"description": description, "expected_revision": task["revision"]}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["description"] == description
    assert saved.json()["assignee_id"] == ids["viewer@example.com"]
    comment = {"id": str(uuid4()), "body": "**Ready for review.**"}
    assert viewer.post(f"{path}/comments", json=comment).status_code == 403
    assert beta.get(f"{path}/comments").status_code == 404
    posted = editor.post(f"{path}/comments", json=comment)
    assert posted.status_code == 201, posted.text
    assert viewer.get(f"{path}/comments").json()["items"] == [posted.json()]

    membership = next(
        member
        for member in admin.get("/api/v1/workspace/members").json()
        if member["email"] == "viewer@example.com"
    )
    removed = admin.delete(f"/api/v1/workspace/members/{membership['membership_id']}")
    assert removed.status_code == 204, removed.text
    assert admin.get(path).json()["assignee_id"] is None


def test_ai_drafts_require_review_and_create_selected_tasks_atomically(
    setup, monkeypatch
):
    store, ids, client, app = setup
    editor = client("editor")
    viewer = client("viewer")
    beta = client("admin", "beta")
    opportunity = seed_opportunity(store, principal(store, ids))
    other = seed_opportunity(store, principal(store, ids), "Another opportunity")
    existing = {
        "id": str(uuid4()),
        "opportunity_id": opportunity,
        "title": "Already planned",
    }
    assert editor.post("/api/v1/tasks", json=existing).status_code == 201
    monkeypatch.setattr(app.state.triage_service, "configured", lambda: True)

    from app_core import task_drafts

    async def fake_draft(context, policy):
        assert context["description"] == "Requests lose their next action."
        assert [item["title"] for item in context["existing_tasks"]] == [
            "Already planned"
        ]
        return task_drafts.DraftResult.model_validate(
            {
                "drafts": [
                    {"title": "ALREADY   PLANNED", "description": "A duplicate."},
                    {
                        "title": "Clarify the next action",
                        "description": "Define the transition.",
                    },
                    {
                        "title": "Verify the new state",
                        "description": "Write a focused check.",
                    },
                ],
                "questions": ["Which views need the new state?"],
            }
        )

    monkeypatch.setattr(task_drafts, "draft_subissues", fake_draft)
    path = f"/api/v1/opportunities/{opportunity}/tasks"
    assert viewer.post(f"{path}/draft").status_code == 403
    assert beta.post(f"{path}/draft").status_code == 404
    response = editor.post(f"{path}/draft")
    assert response.status_code == 200, response.text
    assert [item["title"] for item in response.json()["drafts"]] == [
        "Clarify the next action",
        "Verify the new state",
    ]
    assert response.json()["questions"] == ["Which views need the new state?"]
    assert (
        len(editor.get(f"/api/v1/tasks?opportunity_id={opportunity}").json()["items"])
        == 1
    )

    selected = {
        "id": str(uuid4()),
        "title": "Specify next action",
        "description": "**Done when:** the next action is defined.",
    }
    occupied = {"id": str(uuid4()), "opportunity_id": other, "title": "Another task"}
    assert editor.post("/api/v1/tasks", json=occupied).status_code == 201
    conflict = {"id": occupied["id"], "title": "Conflicting task", "description": ""}
    assert (
        editor.post(f"{path}/batch", json={"tasks": [selected, conflict]}).status_code
        == 409
    )
    assert (
        len(editor.get(f"/api/v1/tasks?opportunity_id={opportunity}").json()["items"])
        == 1
    )
    assert viewer.post(f"{path}/batch", json={"tasks": [selected]}).status_code == 403
    assert beta.post(f"{path}/batch", json={"tasks": [selected]}).status_code == 404
    assert (
        editor.post(
            f"{path}/batch", json={"tasks": [dict(selected, title="Already Planned")]}
        ).status_code
        == 409
    )

    created = editor.post(f"{path}/batch", json={"tasks": [selected]})
    assert created.status_code == 201, created.text
    task = created.json()["items"][0]
    assert task["status"] == "backlog"
    assert task["assignee_id"] is None
    assert task["title"] == selected["title"]
    assert task["description"] == selected["description"]
    assert (
        editor.post(f"{path}/batch", json={"tasks": [selected]}).json()
        == created.json()
    )
    assert (
        len(editor.get(f"/api/v1/tasks?opportunity_id={opportunity}").json()["items"])
        == 2
    )
