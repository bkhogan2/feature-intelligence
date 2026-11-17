import pytest
from fastapi.testclient import TestClient

from app_core.main import HASHER, create_app
from app_core.platform_admin import PlatformAccess


def sign_in(app, email):
    client = TestClient(app, headers={"X-App-Request": "1"})
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": email, "password": "test-password"}
        ).status_code
        == 200
    )
    return client


@pytest.fixture
def platform(pg_store, monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_ENABLED", "false")
    store, _ = pg_store
    hashed = HASHER.hash("test-password")
    for name, role in [
        ("owner", "viewer"),
        ("operator", "viewer"),
        ("customer", "admin"),
    ]:
        store.provision(f"{name}@example.com", hashed, "alpha", "Alpha", role)
    owner = store.user_by_email("owner@example.com")["id"]
    operator = store.user_by_email("operator@example.com")["id"]
    monkeypatch.setenv("PLATFORM_OWNER_SUBJECTS", owner)
    monkeypatch.setenv("PLATFORM_ADMIN_SUBJECTS", operator)
    return store, create_app(store)


def test_platform_roles_are_explicit_and_independent_of_workspace_roles(platform):
    _, app = platform
    assert TestClient(app).get("/api/v1/platform/plans").status_code == 401
    for name, role in [("owner", "owner"), ("operator", "admin")]:
        client = sign_in(app, f"{name}@example.com")
        assert client.get("/api/v1/me").json()["platform_role"] == role
        result = client.get(
            "/api/v1/platform/plans", headers={"X-Workspace": "nonexistent"}
        )
        assert result.status_code == 200
        assert result.json()["role"] == role
        assert result.json()["features"] == [
            {"key": "records.write", "description": "Create and delete example records"}
        ]
        assert {p["key"] for p in result.json()["plans"]} == {"pro", "enterprise"}
        # Platform access is not a bypass for ordinary workspace authorization.
        assert (
            client.post(
                "/api/v1/records",
                headers={"X-Workspace": "alpha"},
                json={"title": "denied"},
            ).status_code
            == 403
        )
    customer = sign_in(app, "customer@example.com")
    assert customer.get("/api/v1/me").json()["platform_role"] is None
    assert (
        customer.get(
            "/api/v1/platform/plans",
            headers={"X-Platform-Role": "owner", "X-Workspace": "alpha"},
            params={"role": "owner"},
        ).status_code
        == 403
    )


def test_no_browser_can_grant_platform_access_or_change_plans(platform):
    _, app = platform
    for name in ("owner", "operator", "customer"):
        client = sign_in(app, f"{name}@example.com")
        assert (
            client.patch("/api/v1/platform/plans", json={"features": []}).status_code
            == 405
        )
        assert (
            client.post(
                "/api/v1/platform/invitations", json={"role": "owner"}
            ).status_code
            == 404
        )
    customer = sign_in(app, "customer@example.com")
    for role in ("owner", "platform_admin", "platform_owner"):
        assert (
            customer.post(
                "/api/v1/workspace/invitations",
                headers={"X-Workspace": "alpha"},
                json={"invited_email": "new@example.com", "role": role},
            ).status_code
            == 422
        )


def test_no_default_platform_access_and_revocation(platform, monkeypatch):
    store, app = platform
    client = sign_in(app, "owner@example.com")
    monkeypatch.delenv("PLATFORM_OWNER_SUBJECTS")
    monkeypatch.delenv("PLATFORM_ADMIN_SUBJECTS")
    revoked = TestClient(create_app(store), cookies=client.cookies)
    assert revoked.get("/api/v1/me").json()["platform_role"] is None
    assert revoked.get("/api/v1/platform/plans").status_code == 403
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/platform/plans").status_code == 401


def test_platform_config_rejects_wildcards_and_ownerless_admins(monkeypatch):
    monkeypatch.setenv("PLATFORM_OWNER_SUBJECTS", "*")
    monkeypatch.delenv("PLATFORM_ADMIN_SUBJECTS", raising=False)
    with pytest.raises(RuntimeError, match="wildcards"):
        PlatformAccess.from_env()
    monkeypatch.setenv("PLATFORM_OWNER_SUBJECTS", "")
    monkeypatch.setenv("PLATFORM_ADMIN_SUBJECTS", "someone")
    with pytest.raises(RuntimeError, match="owner"):
        PlatformAccess.from_env()


@pytest.fixture
def editable_platform(platform, pg_store, monkeypatch):
    import secrets
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from uuid import uuid4

    store, _ = platform
    _, owner_dsn = pg_store
    login = "test_plan_editor_" + uuid4().hex
    password = secrets.token_urlsafe(24)
    with psycopg.connect(owner_dsn) as db:
        db.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOINHERIT").format(
                sql.Identifier(login), sql.Literal(password)
            )
        )
        db.execute(sql.SQL("GRANT app_plan_editor TO {}").format(sql.Identifier(login)))
    config = conninfo_to_dict(owner_dsn)
    config.update(user=login, password=password)
    monkeypatch.setenv("PLATFORM_DATABASE_URL", make_conninfo(**config))
    try:
        yield store, create_app(store), owner_dsn
    finally:
        with psycopg.connect(owner_dsn) as db:
            db.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(login)))


def test_feature_saves_authorization_conflicts_audit_and_live_gate(editable_platform):
    import psycopg
    from app_core.plan_admin import configure

    store, app, owner_dsn = editable_platform
    owner = sign_in(app, "owner@example.com")
    customer = sign_in(app, "customer@example.com")
    operator = sign_in(app, "operator@example.com")
    configure(owner_dsn, "assign", key="pro", workspace="alpha")
    catalog = owner.get("/api/v1/platform/plans").json()
    assert catalog["can_edit"] is True
    pro = next(p for p in catalog["plans"] if p["key"] == "pro")
    path = "/api/v1/platform/plans/pro/features"
    change = {"features": [], "revision": pro["revision"]}
    assert (
        TestClient(app)
        .patch(path, json=change, headers={"X-App-Request": "1"})
        .status_code
        == 401
    )
    assert (
        customer.patch(
            path, json=change, headers={"X-Platform-Role": "owner"}
        ).status_code
        == 403
    )
    assert (
        owner.patch(path, json={**change, "features": ["made.up"]}).status_code == 422
    )
    assert owner.patch(path, json={**change, "active": True}).status_code == 422
    assert (
        owner.patch(
            path, json=change, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    result = owner.patch(path, json=change)
    assert result.status_code == 200
    assert result.json()["features"] == []
    assert operator.patch(path, json=change).status_code == 409
    assert (
        customer.post(
            "/api/v1/records", headers={"X-Workspace": "alpha"}, json={"title": "gated"}
        ).status_code
        == 403
    )
    with psycopg.connect(owner_dsn) as db:
        audit = db.execute(
            "SELECT details FROM app_core.plan_configuration_audit WHERE action='platform.update_features'"
        ).fetchall()
        assert len(audit) == 1
        assert audit[0][0]["subject"] == store.user_by_email("owner@example.com")["id"]
        assert audit[0][0]["before"] == ["records.write"]
        assert audit[0][0]["after"] == []
    enabled = operator.patch(
        path,
        json={"features": ["records.write"], "revision": result.json()["revision"]},
    )
    assert enabled.status_code == 200
    assert (
        customer.post(
            "/api/v1/records",
            headers={"X-Workspace": "alpha"},
            json={"title": "allowed"},
        ).status_code
        == 201
    )
    # Re-saving the same value does not add a misleading audit entry.
    assert (
        owner.patch(
            path,
            json={
                "features": ["records.write"],
                "revision": enabled.json()["revision"],
            },
        ).status_code
        == 200
    )
    with psycopg.connect(owner_dsn) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM app_core.plan_configuration_audit WHERE action='platform.update_features'"
            ).fetchone()[0]
            == 2
        )


def test_editor_cannot_change_other_tables_and_preserves_disabled_plan(
    editable_platform, monkeypatch
):
    import os
    import psycopg
    from app_core.plan_admin import configure
    from app_core.platform_admin import PlanFeatureEditor

    store, app, owner_dsn = editable_platform
    configure(owner_dsn, "disable", key="pro")
    owner = sign_in(app, "owner@example.com")
    pro = next(
        p
        for p in owner.get("/api/v1/platform/plans").json()["plans"]
        if p["key"] == "pro"
    )
    result = owner.patch(
        "/api/v1/platform/plans/pro/features",
        json={"features": [], "revision": pro["revision"]},
    )
    assert result.status_code == 200 and result.json()["active"] is False
    for statement in [
        "UPDATE app_core.plans SET active=true",
        "DELETE FROM app_core.workspace_plans",
        "DELETE FROM app_core.plan_configuration_audit",
    ]:
        with psycopg.connect(os.environ["PLATFORM_DATABASE_URL"]) as db:
            db.execute("SET LOCAL ROLE app_plan_editor")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute(statement)
    with store.connection() as db:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("DELETE FROM plan_feature_assignments")
    with pytest.raises(RuntimeError, match="restricted"):
        PlanFeatureEditor(owner_dsn)


def test_missing_writer_keeps_readonly_panel(platform):
    _, app = platform
    owner = sign_in(app, "owner@example.com")
    assert owner.get("/api/v1/platform/plans").json()["can_edit"] is False
    assert (
        owner.patch(
            "/api/v1/platform/plans/pro/features",
            json={"features": [], "revision": "0" * 64},
        ).status_code
        == 503
    )
