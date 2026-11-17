import psycopg
import pytest
from fastapi.testclient import TestClient
from app_core.main import create_app, HASHER
from app_core.auth.identity import _principal_from_access
from app_core.entitlements import Entitlements
from app_core.plan_admin import configure


def login(app, email, workspace="alpha"):
    client = TestClient(app, headers={"X-App-Request": "1", "X-Workspace": workspace})
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": email, "password": "test-password"}
        ).status_code
        == 200
    )
    return client


@pytest.fixture
def configured(pg_store, monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    store, operator = pg_store
    hashed = HASHER.hash("test-password")
    for email, workspace, role in [
        ("admin@example.com", "alpha", "admin"),
        ("admin@example.com", "beta", "admin"),
        ("editor@example.com", "alpha", "editor"),
        ("viewer@example.com", "alpha", "viewer"),
        ("other@example.com", "beta", "admin"),
    ]:
        store.provision(email, hashed, workspace, workspace, role)
    return store, operator, create_app(store)


def test_plan_changes_roles_and_isolation(configured):
    store, operator, app = configured
    admin = login(app, "admin@example.com")
    editor = login(app, "editor@example.com")
    viewer = login(app, "viewer@example.com")
    assert admin.get("/api/v1/entitlements").json()["features"] == []
    assert admin.post("/api/v1/records", json={"title": "blocked"}).status_code == 403
    configure(operator, "assign", workspace="alpha", key="pro")
    assert admin.get("/api/v1/entitlements").json()["plan"] == "pro"
    assert editor.post("/api/v1/records", json={"title": "allowed"}).status_code == 201
    created = editor.post("/api/v1/records", json={"title": "delete check"}).json()
    assert viewer.delete("/api/v1/records/" + created["id"]).status_code == 403
    assert (
        viewer.post("/api/v1/records", json={"title": "role denied"}).status_code == 403
    )
    assert (
        admin.get("/api/v1/entitlements", headers={"X-Workspace": "beta"}).json()[
            "features"
        ]
        == []
    )
    other = login(app, "other@example.com", "beta")
    assert (
        other.get("/api/v1/entitlements", headers={"X-Workspace": "alpha"}).status_code
        == 404
    )
    assert TestClient(app).get("/api/v1/entitlements").status_code == 401
    assert (
        admin.post("/api/v1/entitlements", json={"plan": "enterprise"}).status_code
        == 405
    )
    configure(operator, "put-plan", key="pro", name="Professional", features=[])
    assert editor.delete("/api/v1/records/" + created["id"]).status_code == 403
    assert editor.post("/api/v1/records", json={"title": "revoked"}).status_code == 403
    configure(
        operator, "put-plan", key="pro", name="Professional", features=["records.write"]
    )
    assert editor.delete("/api/v1/records/" + created["id"]).status_code == 204
    configure(operator, "disable", key="pro")
    assert admin.get("/api/v1/entitlements").json()["features"] == []
    configure(operator, "clear", workspace="alpha")
    assert admin.get("/api/v1/entitlements").json()["plan"] is None
    with pytest.raises(ValueError, match="registered"):
        configure(
            operator, "put-plan", key="pro", name="Pro", features=["invented.feature"]
        )


def test_runtime_cannot_grant_access_and_rls(configured):
    store, operator, _ = configured
    configure(operator, "assign", workspace="alpha", key="pro")
    configure(operator, "assign", workspace="beta", key="enterprise")
    uid = store.user_by_email("admin@example.com")["id"]
    principal = _principal_from_access(store.get_active_global_access(uid, "alpha"))
    with store.connection(principal) as db:
        assert len(db.execute("SELECT * FROM workspace_plans").fetchall()) == 1
    with store.connection() as db:
        assert db.execute("SELECT * FROM workspace_plans").fetchall() == []
    for statement in [
        "UPDATE workspace_plans SET plan_key='enterprise'",
        "UPDATE plans SET active=true",
        "INSERT INTO plan_feature_assignments VALUES ('pro','unknown')",
        "SET LOCAL ROLE app_plan_operator",
    ]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with store.connection(principal) as db:
                db.execute(statement)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        configure(store.database_url, "assign", workspace="alpha", key="enterprise")


def test_disabled_bypasses_plans_not_roles(configured, monkeypatch):
    store, _, _ = configured
    monkeypatch.setenv("BILLING_ENABLED", "false")
    app = create_app(store)
    admin = login(app, "admin@example.com")
    viewer = login(app, "viewer@example.com")
    assert admin.get("/api/v1/entitlements").json() == {
        "billing_enabled": False,
        "plan": None,
        "features": ["records.write"],
    }
    assert admin.post("/api/v1/records", json={"title": "allowed"}).status_code == 201
    assert viewer.post("/api/v1/records", json={"title": "blocked"}).status_code == 403
    with pytest.raises(ValueError, match="Unregistered"):
        Entitlements(store).require(None, "invented.feature")
    monkeypatch.setenv("BILLING_ENABLED", "typo")
    with pytest.raises(RuntimeError, match="true or false"):
        Entitlements(store)
