"""Real PostgreSQL boundaries; model transport is mocked and makes no paid calls."""

import asyncio
import json
import time
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from app_core.auth.identity import Principal
from app_core.triage_models import validate_result
from test_feedback import feedback_setup as shared_feedback_setup


@pytest.fixture
def triage_setup(pg_store):
    return shared_feedback_setup.__wrapped__(pg_store)


def make_request(
    client, title="Clear request", description="I lose track of the next action."
):
    response = client.post(
        "/api/v1/feedback", json={"title": title, "description": description}
    )
    assert response.status_code == 201
    return response.json()


def principal(store, ids, who="admin", workspace="alpha"):
    a = store.get_active_global_access(ids[who + "@example.com"], workspace)
    return Principal(a.user_id, a.workspace, a.role)


def seed_opportunity(store, p, name="Request ownership"):
    oid = uuid4()
    with store.connection(p) as db:
        db.execute(
            "INSERT INTO opportunities(id,workspace_id,name,problem,created_by) VALUES(%s,%s,%s,%s,%s)",
            (oid, p.tenant_id, name, "Requests lose their next action.", p.subject),
        )
    return str(oid)


def output(item, outcome="new_opportunity", opportunity_id=None):
    common = {
        "outcome": outcome,
        "rationale_markdown": "## Interpretation\nThis concerns request ownership, based on the quoted feedback.",
        "evidence": [
            {"feedback_id": str(item["id"]), "quote": item["description"][:100]}
        ],
    }
    if outcome == "new_opportunity":
        common.update(
            proposed_name="Request ownership",
            proposed_problem="People lose track of the next action.",
        )
    elif outcome == "existing_opportunity":
        common.update(opportunity_id=opportunity_id)
    else:
        common.update(
            ambiguity="It is unclear which workflow is affected.",
            questions=["Which workflow loses the next action?"],
        )
    return common


def await_terminal(c, rid):
    for _ in range(200):
        state = c.get(f"/api/v1/feedback/{rid}/triage").json()
        if state["run"] and state["run"]["status"] != "running":
            return state
        time.sleep(0.01)
    raise AssertionError("Run did not terminate")


def fake_worker(monkeypatch, result, events=None, delay=0.03, before=None):
    captured = {}
    writes = []

    class Input:
        def write(self, data):
            writes.append(json.loads(data))

        async def drain(self):
            pass

    class Output:
        def __init__(self):
            self.events = list(events or []) + [
                {
                    "type": "done",
                    "error": False,
                    "result": {"decision": result},
                    "cost_usd": 0.001,
                }
            ]

        async def readline(self):
            await asyncio.sleep(delay)
            if not self.events:
                return b""
            return (json.dumps(self.events.pop(0)) + "\n").encode()

    class Process:
        returncode = 0
        stdin = Input()
        stdout = Output()

    async def spawn(*args, **kwargs):
        captured.update(kwargs)
        if before:
            before()
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setenv("TRIAGE_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key-no-network")
    return captured, writes


@pytest.mark.parametrize(
    "outcome", ["new_opportunity", "existing_opportunity", "insufficient_context"]
)
def test_three_saved_outcomes_and_explicit_confirmation(
    triage_setup, monkeypatch, outcome
):
    store, ids, client, app = triage_setup
    c = client("admin")
    item = make_request(c)
    p = principal(store, ids)
    oid = seed_opportunity(store, p) if outcome == "existing_opportunity" else None
    result = output(item, outcome, oid)
    captured, writes = fake_worker(monkeypatch, result)
    monkeypatch.setattr(app.state.triage_service, "configured", lambda: True)
    with TestClient(
        app, headers={"X-App-Request": "1", "X-Workspace": "alpha"}
    ) as active:
        active.cookies.set("app_session", c.cookies.get("app_session"))
        response = active.post(f"/api/v1/feedback/{item['id']}/triage")
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        state = await_terminal(active, item["id"])
        assert state["run"]["status"] == "complete", state
        assert state["run"]["result"] == result
        assert state["run"]["model"] == "claude-haiku-5-5"
        assert state["run"]["prompt_version"] == "triage-v1"
        assert state["linked_opportunity"] is None
        assert (
            "DATABASE_URL" not in captured["env"]
            and "GOOGLE_APPLICATION_CREDENTIALS" not in captured["env"]
        )
        assert captured["start_new_session"] is True
        assert writes[0]["task"] == "triage"
        assert "fake-test-key" not in str(state)
        path = f"/api/v1/feedback/{item['id']}/triage/{run_id}/confirm"
        if outcome == "insufficient_context":
            assert active.post(path).status_code == 409
        else:
            first = active.post(path)
            assert first.status_code == 200, first.text
            assert active.post(path).json() == first.json()
            assert (
                active.get(f"/api/v1/feedback/{item['id']}/triage").json()[
                    "linked_opportunity"
                ]["id"]
                == first.json()["opportunity_id"]
            )
            assert len(active.get("/api/v1/opportunities").json()["items"]) == 1
    assert store.triage_state(p, item["id"])["run"]["status"] == "complete"


def test_auth_roles_workspace_and_unconfigured(triage_setup, monkeypatch):
    store, ids, client, app = triage_setup
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("TRIAGE_ENABLED", "false")
    item = make_request(client("admin"))
    path = f"/api/v1/feedback/{item['id']}/triage"
    assert TestClient(app).get(path).status_code == 401
    assert client("admin", "beta").get(path).status_code == 404
    assert client("admin", "beta").post(path).status_code == 404
    assert client("outsider").get(path).status_code == 404
    assert client("viewer").get(path).json() == {
        "run": None,
        "linked_opportunity": None,
        "linked_opportunities": [],
    }
    assert client("viewer").post(path).status_code == 403
    assert client("admin").post(path).status_code == 503
    assert client("admin").get(path).json()["run"] is None
    p = principal(store, ids)
    row, _ = store.start_triage(p, item["id"], "test", "test", 130)
    store.finish_triage(p, row["id"], output(item))
    confirm = path + f"/{row['id']}/confirm"
    assert client("viewer").post(confirm).status_code == 403
    assert client("admin", "beta").post(confirm).status_code == 404
    assert (
        client("admin").post(confirm, headers={"X-App-Request": ""}).status_code == 403
    )
    assert (
        client("admin")
        .post(confirm, headers={"Origin": "https://evil.invalid"})
        .status_code
        == 403
    )
    oid = seed_opportunity(store, p)
    assert client("admin", "beta").get("/api/v1/opportunities").json()["items"] == []
    assert (
        client("admin", "beta").get("/api/v1/opportunities/" + oid).status_code == 404
    )


def test_duplicate_inflight_and_retry_failed(triage_setup, monkeypatch):
    _, _, client, app = triage_setup
    c = client("admin")
    item = make_request(c)
    fake_worker(monkeypatch, output(item), events=[{"type": "error"}], delay=0.15)
    monkeypatch.setattr(app.state.triage_service, "configured", lambda: True)
    with TestClient(
        app, headers={"X-App-Request": "1", "X-Workspace": "alpha"}
    ) as active:
        active.cookies.set("app_session", c.cookies.get("app_session"))
        path = f"/api/v1/feedback/{item['id']}/triage"
        first = active.post(path)
        second = active.post(path)
        assert first.json()["id"] == second.json()["id"]
        assert await_terminal(active, item["id"])["run"]["status"] == "failed"
        fake_worker(monkeypatch, output(item))
        retry = active.post(path)
        assert retry.json()["id"] != first.json()["id"]
        assert await_terminal(active, item["id"])["run"]["status"] == "complete"


@pytest.mark.parametrize(
    "fault", ["quote", "opportunity", "unknown_tool", "revoked_session", "timeout"]
)
def test_invalid_outputs_and_access_changes_fail_closed(
    triage_setup, monkeypatch, fault
):
    store, _, client, app = triage_setup
    c = client("admin")
    item = make_request(c)
    result = output(item)
    events = []
    if fault == "quote":
        result["evidence"][0]["quote"] = "Invented customer quote"
    if fault == "opportunity":
        result = output(item, "existing_opportunity", str(uuid4()))
    if fault == "unknown_tool":
        events = [{"type": "tool", "name": "execute_sql", "arguments": {}}]
    before = (
        (lambda: store.revoke_session(c.cookies.get("app_session")))
        if fault == "revoked_session"
        else None
    )
    fake_worker(monkeypatch, result, events=events, before=before)
    monkeypatch.setattr(app.state.triage_service, "configured", lambda: True)
    if fault == "timeout":

        async def timeout(*args, **kwargs):
            raise TimeoutError

        monkeypatch.setattr(asyncio, "create_subprocess_exec", timeout)
    with TestClient(
        app, headers={"X-App-Request": "1", "X-Workspace": "alpha"}
    ) as active:
        active.cookies.set("app_session", c.cookies.get("app_session"))
        assert active.post(f"/api/v1/feedback/{item['id']}/triage").status_code == 202
        reader = client("editor") if fault == "revoked_session" else active
        state = await_terminal(reader, item["id"])
        assert state["run"]["status"] == "failed"
        assert state["run"]["result"] is None
        assert state["linked_opportunity"] is None
        assert reader.get("/api/v1/opportunities").json()["items"] == []


def test_stale_runs_are_reconciled_and_do_not_block_retry(triage_setup):
    store, ids, client, _ = triage_setup
    item = make_request(client("admin"))
    p = principal(store, ids)
    expired, _ = store.start_triage(p, item["id"], "test", "test", -1)
    viewer = client("viewer").get(f"/api/v1/feedback/{item['id']}/triage").json()
    assert viewer["run"]["status"] == "failed"
    state = store.triage_state(p, item["id"])
    assert state["run"]["status"] == "failed"
    with store.connection(p) as db:
        assert (
            db.execute(
                "SELECT status FROM triage_runs WHERE id=%s", (expired["id"],)
            ).fetchone()["status"]
            == "failed"
        )
    retry, created = store.start_triage(p, item["id"], "test", "test", 130)
    assert created and retry["id"] != expired["id"]
    store.finish_triage(p, expired["id"], output(item))
    assert store.triage_state(p, item["id"])["run"]["id"] == retry["id"]


def test_triage_rls_guards_run_and_opportunity_writes(triage_setup):
    store, ids, client, _ = triage_setup
    item = make_request(client("admin"))
    p = principal(store, ids)
    viewer = principal(store, ids, "viewer")
    beta = principal(store, ids, workspace="beta")
    oid = seed_opportunity(store, p)
    for actor, workspace, creator in [
        (viewer, viewer.tenant_id, viewer.subject),
        (p, beta.tenant_id, p.subject),
        (p, p.tenant_id, viewer.subject),
    ]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with store.connection(actor) as db:
                db.execute(
                    "INSERT INTO opportunities(id,workspace_id,name,problem,created_by) VALUES(%s,%s,%s,%s,%s)",
                    (uuid4(), workspace, "Name", "Problem", creator),
                )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        store.start_triage(viewer, item["id"], "test", "test", 130)
    row, _ = store.start_triage(p, item["id"], "test", "test", 130)
    with store.connection(beta) as db:
        assert db.execute("SELECT * FROM opportunities").fetchall() == []
        assert db.execute("SELECT * FROM triage_runs").fetchall() == []
        assert (
            db.execute(
                "UPDATE triage_runs SET status='failed' WHERE id=%s RETURNING id",
                (row["id"],),
            ).fetchall()
            == []
        )
    with store.connection() as db:
        assert db.execute("SELECT * FROM triage_runs").fetchall() == []
    with store.connection(viewer) as db:
        assert (
            db.execute(
                "UPDATE triage_runs SET status='failed' WHERE id=%s RETURNING id",
                (row["id"],),
            ).fetchall()
            == []
        )
    assert store.opportunity(beta, oid) is None


def test_structured_validation_requires_current_evidence_and_one_or_two_questions():
    item = {"id": str(uuid4()), "description": "Observed problem"}
    valid = output(item, "insufficient_context")
    assert validate_result(valid, {item["id"]: item}, {}, item["id"]) == valid
    for patch in [
        {"questions": []},
        {"questions": ["a", "b", "c"]},
        {"extra": "field"},
        {"evidence": []},
    ]:
        with pytest.raises(ValueError):
            validate_result({**valid, **patch}, {item["id"]: item}, {}, item["id"])
    other = {**item, "id": str(uuid4())}
    with pytest.raises(ValueError):
        validate_result(output(other), {other["id"]: other}, {}, item["id"])


def test_read_only_tools_never_return_other_workspace_or_user_fields(
    triage_setup, monkeypatch
):
    store, ids, client, app = triage_setup
    c = client("admin")
    item = make_request(c)
    foreign = make_request(client("admin", "beta"), description="Private beta evidence")
    p = principal(store, ids)
    beta = principal(store, ids, workspace="beta")
    seed_opportunity(store, p)
    foreign_opportunity = seed_opportunity(store, beta, "Private beta opportunity")
    events = [
        {"type": "tool", "name": "search_opportunities", "arguments": {"query": ""}},
        {"type": "tool", "name": "search_feedback", "arguments": {"query": ""}},
        {
            "type": "tool",
            "name": "get_opportunity",
            "arguments": {"id": foreign_opportunity},
        },
    ]
    _, writes = fake_worker(monkeypatch, output(item), events=events)
    monkeypatch.setattr(app.state.triage_service, "configured", lambda: True)
    with TestClient(
        app, headers={"X-App-Request": "1", "X-Workspace": "alpha"}
    ) as active:
        active.cookies.set("app_session", c.cookies.get("app_session"))
        assert active.post(f"/api/v1/feedback/{item['id']}/triage").status_code == 202
        assert await_terminal(active, item["id"])["run"]["status"] == "complete"
    assert len(writes) == 4
    assert "Private beta" not in str(writes)
    assert foreign["id"] not in str(writes)
    assert set(writes[2]["items"][0]) == {
        "id",
        "title",
        "description",
        "description_truncated",
    }
    assert writes[3] == {"error": "Opportunity not found in this workspace."}


def test_capacity_and_latest_confirmation(triage_setup, monkeypatch):
    store, ids, client, app = triage_setup
    c = client("admin")
    first = make_request(c)
    second = make_request(c, title="Second")
    monkeypatch.setattr(app.state.triage_service, "configured", lambda: True)
    app.state.triage_service.tasks = {"occupied1": object(), "occupied2": object()}
    assert c.post(f"/api/v1/feedback/{second['id']}/triage").status_code == 429
    app.state.triage_service.tasks = {}
    p = principal(store, ids)
    older, _ = store.start_triage(p, first["id"], "test", "test", 130)
    store.finish_triage(p, older["id"], output(first))
    newer, _ = store.start_triage(p, first["id"], "test", "test", 130)
    assert (
        c.post(
            f"/api/v1/feedback/{first['id']}/triage/{older['id']}/confirm"
        ).status_code
        == 409
    )
    store.finish_triage(p, newer["id"], output(first))
    assert (
        c.post(
            f"/api/v1/feedback/{first['id']}/triage/{newer['id']}/confirm"
        ).status_code
        == 200
    )
    assert (
        c.post(
            f"/api/v1/feedback/{first['id']}/triage/{older['id']}/confirm"
        ).status_code
        == 409
    )
    assert len(store.opportunities(p)["items"]) == 1


def test_tool_call_budget_fails_instead_of_running_unbounded(triage_setup, monkeypatch):
    _, _, client, app = triage_setup
    c = client("admin")
    item = make_request(c)
    fake_worker(
        monkeypatch,
        output(item),
        events=[
            {"type": "tool", "name": "search_opportunities", "arguments": {"query": ""}}
        ]
        * 9,
        delay=0.001,
    )
    monkeypatch.setattr(app.state.triage_service, "configured", lambda: True)
    with TestClient(
        app, headers={"X-App-Request": "1", "X-Workspace": "alpha"}
    ) as active:
        active.cookies.set("app_session", c.cookies.get("app_session"))
        assert active.post(f"/api/v1/feedback/{item['id']}/triage").status_code == 202
        assert await_terminal(active, item["id"])["run"]["status"] == "failed"


def test_exported_schema_is_standard_json_schema_but_keeps_union_constraints():
    from app_core.triage_models import triage_json_schema

    schema = triage_json_schema()
    assert "discriminator" not in json.dumps(schema)
    assert len(schema["properties"]["decision"]["oneOf"]) == 3
    assert (
        schema["$defs"]["ExistingOpportunity"]["properties"]["outcome"]["const"]
        == "existing_opportunity"
    )
    assert (
        schema["$defs"]["NewOpportunity"]["properties"]["outcome"]["const"]
        == "new_opportunity"
    )
    assert (
        schema["$defs"]["InsufficientContext"]["properties"]["outcome"]["const"]
        == "insufficient_context"
    )


def test_failed_model_result_keeps_safe_reason_and_reported_cost(
    triage_setup, monkeypatch
):
    _, _, client, app = triage_setup
    c = client("admin")
    item = make_request(c)
    fake_worker(
        monkeypatch,
        output(item),
        events=[
            {
                "type": "done",
                "error": True,
                "result": None,
                "failure_code": "error_max_budget_usd",
                "cost_usd": 0.012,
                "raw_provider_error": "must-not-be-exposed",
            }
        ],
    )
    monkeypatch.setattr(app.state.triage_service, "configured", lambda: True)
    with TestClient(
        app, headers={"X-App-Request": "1", "X-Workspace": "alpha"}
    ) as active:
        active.cookies.set("app_session", c.cookies.get("app_session"))
        assert active.post(f"/api/v1/feedback/{item['id']}/triage").status_code == 202
        state = await_terminal(active, item["id"])
        assert state["run"]["status"] == "failed"
        assert "spending limit" in state["run"]["error"]
        assert state["run"]["cost_usd"] == 0.012
        assert "must-not-be-exposed" not in str(state)


def test_opportunity_description_edit_is_scoped_and_rejects_stale_writes(triage_setup):
    store, ids, client, _ = triage_setup
    oid = seed_opportunity(store, principal(store, ids))
    path = f"/api/v1/opportunities/{oid}"
    payload = {
        "markdown": "## Problem\n\nMake the next action **visible**.",
        "expected_revision": 0,
    }
    editor = client("editor")
    initial = editor.get(path).json()
    assert initial["description_markdown"] is None
    assert initial["description_revision"] == 0
    assert client("viewer").put(f"{path}/description", json=payload).status_code == 403
    assert (
        client("admin", "beta").put(f"{path}/description", json=payload).status_code
        == 404
    )
    assert (
        editor.put(
            f"{path}/description", json={**payload, "markdown": "  "}
        ).status_code
        == 422
    )
    saved = editor.put(f"{path}/description", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "description_markdown": payload["markdown"],
        "description_revision": 1,
    }
    assert (
        editor.put(
            f"{path}/description", json={**payload, "markdown": "Stale draft"}
        ).status_code
        == 409
    )
    reopened = client("viewer").get(path).json()
    assert reopened["description_markdown"] == payload["markdown"]
    assert reopened["problem"] == initial["problem"]


def test_opportunity_discussion_persists_separately_from_request_comments(triage_setup):
    store, ids, client, _ = triage_setup
    oid = seed_opportunity(store, principal(store, ids))
    editor = client("editor")
    viewer = client("viewer")
    path = f"/api/v1/opportunities/{oid}/comments"
    payload = {"id": str(uuid4()), "body": "**Opportunity context**"}
    assert viewer.post(path, json=payload).status_code == 403
    assert client("admin", "beta").get(path).status_code == 404
    created = editor.post(path, json=payload)
    assert created.status_code == 201, created.text
    assert editor.post(path, json=payload).json() == created.json()
    assert (
        editor.post(path, json={**payload, "body": "Another draft"}).status_code == 409
    )
    assert viewer.get(path).json() == {"items": [created.json()]}
    request = make_request(editor)
    request_path = f"/api/v1/feedback/{request['id']}/comments"
    assert editor.get(request_path).json() == {"items": []}
    assert editor.post(request_path, json=payload).status_code == 201
    assert viewer.get(path).json() == {"items": [created.json()]}
