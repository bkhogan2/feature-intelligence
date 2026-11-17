"""No paid model calls: verify app-owned tools and authenticated boundaries in PG."""

from fastapi.testclient import TestClient
import asyncio
import json
import pytest

from app_core.agent_tools import seed_demo_records, search_demo_records
from app_core.auth.identity import _principal_from_access
from app_core.main import HASHER, create_app


@pytest.fixture
def agent_setup(pg_store, monkeypatch):
    monkeypatch.setenv("AUTH_PROVIDER", "local")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_ENABLED", "false")
    store, _ = pg_store
    store.provision(
        "agent@example.com", HASHER.hash("demo-password"), "alpha", "Alpha", "admin"
    )
    store.provision(
        "agent@example.com", HASHER.hash("demo-password"), "beta", "Beta", "admin"
    )
    # provision returns a user id (the same user can belong to both workspaces).
    user = store.user_by_email("agent@example.com")
    alpha = _principal_from_access(store.get_active_global_access(user["id"], "alpha"))
    beta = _principal_from_access(store.get_active_global_access(user["id"], "beta"))
    return store, create_app(store), alpha, beta


def test_agent_search_is_scoped_and_never_exports_application_fields(agent_setup):
    store, _, alpha, beta = agent_setup
    seed_demo_records(store, alpha)
    seed_demo_records(store, alpha)
    store.create_record(alpha, "Private non-demo record", {"secret": "must-not-leave"})
    store.create_record(
        alpha,
        "Arbitrary title",
        {"agent_demo_id": "demo-website", "secret": "must-not-leave"},
    )
    result = search_demo_records(store, alpha, "demo")
    assert result["count"] == 3
    assert all(set(row) == {"id", "title", "status"} for row in result["records"])
    assert "must-not-leave" not in str(result)
    assert search_demo_records(store, beta, "demo")["count"] == 0
    assert search_demo_records(store, alpha, "website")["count"] == 1
    assert search_demo_records(store, alpha, "' OR 1=1 --")["count"] == 0


def test_agent_requires_login_workspace_and_server_key(agent_setup):
    _, app, _, _ = agent_setup
    anonymous = TestClient(app, headers={"X-App-Request": "1"})
    assert anonymous.get("/api/v1/assistant/config").status_code == 401
    c = TestClient(app, headers={"X-App-Request": "1", "X-Workspace": "alpha"})
    assert (
        c.post(
            "/api/v1/auth/login",
            json={"email": "agent@example.com", "password": "demo-password"},
        ).status_code
        == 200
    )
    config = c.get("/api/v1/assistant/config").json()
    assert config["enabled"] is False
    assert config["max_budget_usd"] == 0.05
    assert config["max_turns"] == 4
    assert "key" not in str(config).lower()
    assert (
        c.post("/api/v1/assistant/runs", json={"message": "find demo"}).status_code
        == 503
    )
    assert (
        c.post("/api/v1/assistant/runs", json={"message": "x" * 1001}).status_code
        == 422
    )
    assert (
        c.post(
            "/api/v1/assistant/runs/missing/actions",
            json={"action_id": "missing", "ok": True},
        ).status_code
        == 404
    )
    assert (
        c.get(
            "/api/v1/assistant/config", headers={"X-Workspace": "unknown"}
        ).status_code
        == 404
    )


def test_harness_gets_scoped_tool_results_and_its_own_credentials(
    agent_setup, monkeypatch
):
    store, app, alpha, _ = agent_setup
    seed_demo_records(store, alpha)
    monkeypatch.setenv("AGENT_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-no-network")
    monkeypatch.setenv("AGENT_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("DATABASE_URL", "must-not-enter-worker")
    writes = []
    captured = {}

    class Input:
        def write(self, data):
            writes.append(json.loads(data))

        async def drain(self):
            pass

    class Process:
        returncode = 0
        stdin = Input()

        def __init__(self):
            self.stdout = asyncio.StreamReader()
            for event in [
                {
                    "type": "tool",
                    "name": "search_feedback",
                    "arguments": {"query": "demo"},
                },
                {"type": "text", "text": "Found three synthetic records."},
                {"type": "done", "cost_usd": 0.0003, "error": False, "turns": 2},
            ]:
                self.stdout.feed_data((json.dumps(event) + "\n").encode())
            self.stdout.feed_eof()

    async def spawn(*args, **kwargs):
        captured.update(kwargs)
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with TestClient(app, headers={"X-App-Request": "1", "X-Workspace": "alpha"}) as c:
        c.post(
            "/api/v1/auth/login",
            json={"email": "agent@example.com", "password": "demo-password"},
        )
        response = c.post(
            "/api/v1/assistant/runs", json={"message": "Find demo records"}
        )
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == ["start", "status", "text", "done"]
    assert writes[1]["items"] == []
    assert "DATABASE_URL" not in captured["env"]
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in captured["env"]
    assert captured["env"]["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "768"
    assert captured["start_new_session"] is True
    assert "fake-key" not in response.text


def test_agent_policy_is_configurable_and_validated(monkeypatch):
    from app_core.agent_settings import AgentSettings

    monkeypatch.setenv("AGENT_MAX_TURNS", "3")
    monkeypatch.setenv("AGENT_MAX_BUDGET_USD", "0.02")
    monkeypatch.setenv("AGENT_MAX_OUTPUT_TOKENS", "512")
    monkeypatch.setenv("AGENT_MAX_MESSAGE_CHARS", "600")
    policy = AgentSettings.from_env()
    assert policy.public_config()["max_turns"] == 3
    assert policy.public_config()["max_budget_usd"] == 0.02
    assert policy.worker_env()["AGENT_MAX_TURNS"] == "3"
    assert policy.worker_env()["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "512"
    assert policy.max_message_chars == 600
    for value in ["nan", "inf", "-1", "2", "oops"]:
        monkeypatch.setenv("AGENT_MAX_BUDGET_USD", value)
        with pytest.raises(ValueError, match="AGENT_MAX_BUDGET_USD"):
            AgentSettings.from_env()


def test_server_enforces_configured_message_limit(agent_setup, monkeypatch):
    store, _, _, _ = agent_setup
    monkeypatch.setenv("AGENT_MAX_MESSAGE_CHARS", "600")
    app = create_app(store)
    c = TestClient(app, headers={"X-App-Request": "1", "X-Workspace": "alpha"})
    c.post(
        "/api/v1/auth/login",
        json={"email": "agent@example.com", "password": "demo-password"},
    )
    assert c.get("/api/v1/assistant/config").json()["max_message_chars"] == 600
    assert (
        c.post("/api/v1/assistant/runs", json={"message": "x" * 601}).status_code == 422
    )


@pytest.mark.parametrize("scenario", ["revoked", "terminal", "crash", "timeout"])
def test_stream_rechecks_access_and_terminates_safely(
    agent_setup, monkeypatch, scenario
):
    store, app, alpha, _ = agent_setup
    seed_demo_records(store, alpha)
    monkeypatch.setenv("AGENT_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-no-network")
    writes = []

    class Input:
        def write(self, data):
            writes.append(json.loads(data))

        async def drain(self):
            pass

    class Output:
        def __init__(self):
            tool = {
                "type": "tool",
                "name": "search_feedback",
                "arguments": {"query": "demo"},
            }
            self.events = (
                [{"type": "done", "error": False}, tool]
                if scenario == "terminal"
                else [tool]
            )

        async def readline(self):
            if scenario == "timeout":
                raise TimeoutError
            if scenario == "crash" or not self.events:
                return b""
            return (json.dumps(self.events.pop(0)) + "\n").encode()

    class Process:
        returncode = 0
        stdin = Input()
        stdout = Output()

    with TestClient(app, headers={"X-App-Request": "1", "X-Workspace": "alpha"}) as c:
        c.post(
            "/api/v1/auth/login",
            json={"email": "agent@example.com", "password": "demo-password"},
        )

        async def spawn(*args, **kwargs):
            if scenario == "revoked":
                store.revoke_session(c.cookies.get("app_session"))
            return Process()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        response = c.post("/api/v1/assistant/runs", json={"message": "Find demo"})
        events = [json.loads(line) for line in response.text.splitlines()]
        assert [e["type"] for e in events] == [
            "start",
            "done" if scenario == "terminal" else "error",
        ]
        assert len(writes) == 1
        assert "Demo website" not in response.text
        if scenario == "revoked":
            assert "access changed" in events[-1]["message"]
        if scenario != "revoked":
            assert (
                c.post("/api/v1/assistant/runs", json={"message": "Retry"}).status_code
                == 200
            )


def test_domain_tools_validate_ids_and_scope_evidence(agent_setup):
    from app_core.agent_tools import domain_tool

    store, _, alpha, beta = agent_setup
    item = store.create_feedback(alpha, "Evidence", "Actual internal request")
    result = domain_tool(store, alpha, "get_feedback", {"id": str(item["id"])})
    assert result["description"] == "Actual internal request"
    assert result["support_count"] == 0
    assert result["source"].startswith("#inbox?id=")
    assert "submitted_by" not in result
    assert domain_tool(store, beta, "get_feedback", {"id": str(item["id"])})["error"]
    assert domain_tool(store, alpha, "get_feedback", {"id": "bad"})["error"]
    assert domain_tool(store, alpha, "delete_feedback", {"id": str(item["id"])})[
        "error"
    ]
    assert domain_tool(store, alpha, "search_feedback", {"query": "x" * 121})["error"]


def test_selected_context_is_server_validated(agent_setup, monkeypatch):
    store, app, alpha, beta = agent_setup
    monkeypatch.setenv("AGENT_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-no-network")
    item = store.create_feedback(beta, "Other workspace", "Not accessible")
    with TestClient(app, headers={"X-App-Request": "1", "X-Workspace": "alpha"}) as c:
        c.post(
            "/api/v1/auth/login",
            json={"email": "agent@example.com", "password": "demo-password"},
        )
        assert (
            c.post(
                "/api/v1/assistant/runs",
                json={
                    "message": "Explain this",
                    "context": {"kind": "feedback", "id": str(item["id"])},
                },
            ).status_code
            == 404
        )
        assert (
            c.post(
                "/api/v1/assistant/runs",
                json={
                    "message": "Explain this",
                    "context": {"kind": "feedback", "id": "invalid"},
                },
            ).status_code
            == 422
        )
