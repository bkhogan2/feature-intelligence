from datetime import UTC, datetime, timedelta
import hashlib
import pytest
from fastapi.testclient import TestClient
from app_core.main import create_app, HASHER
from app_core.store import PostgresStore
from app_core.auth.identity import VerifiedIdentity

PASSWORD = "testing-only-password"


@pytest.fixture
def setup(pg_store):
    store, _ = pg_store
    hashed = HASHER.hash(PASSWORD)
    ids = {}
    for email, slug, role in [
        ("admin@example.com", "alpha", "admin"),
        ("admin@example.com", "beta", "admin"),
        ("viewer@example.com", "alpha", "viewer"),
        ("other@example.com", "beta", "admin"),
    ]:
        ids[email] = store.provision(email, hashed, slug, slug.title(), role)
    app = create_app(store)
    return store, app, ids


def client(app, email):
    c = TestClient(app, headers={"X-App-Request": "1", "X-Workspace": "alpha"})
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return c


def test_session_csrf_expiration_and_logout(setup):
    store, app, ids = setup
    c = client(app, "admin@example.com")
    assert (
        "HttpOnly"
        in c.cookies.jar._cookies["testserver.local"]["/"]["app_session"]._rest
    )
    assert c.get("/api/v1/me").status_code == 200
    assert (
        c.post(
            "/api/v1/records",
            headers={"Origin": "https://evil.example"},
            json={"title": "bad"},
        ).status_code
        == 403
    )
    assert (
        TestClient(app)
        .post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": PASSWORD},
        )
        .status_code
        == 403
    )
    token = c.cookies.get("app_session")
    with store.connection() as db:
        db.execute("UPDATE sessions SET expires_at=0")
    assert c.get("/api/v1/me").status_code == 401
    c = client(app, "admin@example.com")
    token = c.cookies.get("app_session")
    assert c.post("/api/v1/auth/logout").status_code == 204
    c.cookies.set("app_session", token)
    assert c.get("/api/v1/me").status_code == 401


def test_cross_tenant_reads_writes_and_body_forgery(setup):
    store, app, ids = setup
    a = client(app, "admin@example.com")
    b = client(app, "other@example.com")
    b.headers["X-Workspace"] = "beta"
    created = a.post(
        "/api/v1/records",
        json={"title": "Alpha record", "payload": {"anything": [1, 2]}},
    )
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    assert b.get("/api/v1/records").json() == []
    assert b.get("/api/v1/records/" + rid).status_code == 404
    assert b.delete("/api/v1/records/" + rid).status_code == 404
    b.headers["X-Workspace"] = "alpha"
    assert b.get("/api/v1/records").status_code == 404
    assert (
        a.post(
            "/api/v1/records", json={"title": "forged", "workspace_id": "beta"}
        ).status_code
        == 422
    )
    a.headers["X-Workspace"] = "beta"
    assert a.get("/api/v1/records").json() == []
    assert a.get("/api/v1/records/" + rid).status_code == 404
    a.headers.pop("X-Workspace")
    assert a.get("/api/v1/records").status_code == 404


def test_roles_membership_revocation_last_admin_and_preferences(setup):
    store, app, ids = setup
    a = client(app, "admin@example.com")
    v = client(app, "viewer@example.com")
    assert v.post("/api/v1/records", json={"title": "blocked"}).status_code == 403
    assert v.get("/api/v1/workspace/members").status_code == 403
    members = a.get("/api/v1/workspace/members").json()
    own = next(m for m in members if m["is_current_user"])
    other = next(m for m in members if not m["is_current_user"])
    assert (
        a.patch(
            "/api/v1/workspace/members/" + own["membership_id"], json={"role": "viewer"}
        ).status_code
        == 409
    )
    assert (
        a.delete("/api/v1/workspace/members/" + own["membership_id"]).status_code == 409
    )
    assert (
        a.patch(
            "/api/v1/workspace/members/" + other["membership_id"],
            json={"status": "disabled"},
        ).status_code
        == 200
    )
    assert v.get("/api/v1/records").status_code == 404
    assert (
        a.patch("/api/v1/me/preferences", json={"color_palette": "violet"}).status_code
        == 200
    )
    assert a.get("/api/v1/me/preferences").json()["color_palette"] == "violet"
    assert v.get("/api/v1/me/preferences").json()["color_palette"] == "slate"
    assert a.get("/api/v1/activity").json()[0]["action"] == "membership.updated"


def test_invitation_email_binding_replay_revocation_and_expiry(setup):
    store, app, ids = setup
    a = client(app, "admin@example.com")
    b = client(app, "other@example.com")
    result = a.post(
        "/api/v1/workspace/invitations",
        json={"invited_email": "other@example.com", "role": "editor"},
    )
    assert result.status_code == 201, result.text
    token = result.json()["invitation_token"]
    body = {"invitation_token": token, "accept_terms": True, "accept_privacy": True}
    assert a.post("/api/v1/onboarding/invitations/accept", json=body).status_code == 403
    assert b.post("/api/v1/onboarding/invitations/accept", json=body).status_code == 200
    assert b.post("/api/v1/onboarding/invitations/accept", json=body).status_code == 404
    b.headers["X-Workspace"] = "alpha"
    assert b.post("/api/v1/records", json={"title": "accepted"}).status_code == 201
    r = a.post(
        "/api/v1/workspace/invitations",
        json={"invited_email": "next@example.com", "role": "viewer"},
    ).json()
    assert (
        a.delete(
            "/api/v1/workspace/invitations/" + r["invitation"]["invitation_id"]
        ).status_code
        == 200
    )
    assert (
        a.post(
            "/api/v1/onboarding/invitations/resolve",
            json={"invitation_token": r["invitation_token"]},
        ).status_code
        == 404
    )
    r = a.post(
        "/api/v1/workspace/invitations",
        json={"invited_email": "expired@example.com", "role": "viewer"},
    ).json()
    with store.connection() as db:
        db.execute(
            "UPDATE invitations SET expires_at=%s WHERE id=%s",
            (
                (datetime.now(UTC) - timedelta(days=1)).isoformat(),
                r["invitation"]["invitation_id"],
            ),
        )
    assert (
        a.post(
            "/api/v1/onboarding/invitations/resolve",
            json={"invitation_token": r["invitation_token"]},
        ).status_code
        == 404
    )
    with store.connection() as db:
        assert (
            db.execute("SELECT count(*) FROM legal_acceptances").fetchone()["count"]
            == 1
        )
        assert (
            db.execute(
                "SELECT token_digest FROM invitations WHERE id=%s",
                (result.json()["invitation"]["invitation_id"],),
            ).fetchone()["token_digest"]
            == hashlib.sha256(token.encode()).digest()
        )


def test_persistence_and_auth_provider_plug_in(setup):
    store, app, ids = setup
    a = client(app, "admin@example.com")
    a.post("/api/v1/records", json={"title": "Persists"})
    restarted = PostgresStore(store.database_url)
    assert len(restarted.list_active_global_access(ids["admin@example.com"])) == 2

    class Verifier:
        def verify(self, token):
            assert token == "verified-by-provider"
            return VerifiedIdentity(
                subject=ids["admin@example.com"],
                email="admin@example.com",
                email_verified=True,
            )

    custom = TestClient(
        create_app(restarted, verifier=Verifier()),
        headers={
            "Authorization": "Bearer verified-by-provider",
            "X-Workspace": "alpha",
        },
    )
    assert custom.get("/api/v1/me").status_code == 200
    assert custom.get("/api/v1/records").json()[0]["title"] == "Persists"
    assert custom.get("/api/v1/me/workspaces").status_code == 200
    restarted.close()


def test_input_limits_invalid_credentials_and_throttle(setup):
    store, app, ids = setup
    c = TestClient(app, headers={"X-App-Request": "1"})
    assert (
        c.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "wrong"},
        ).status_code
        == 401
    )
    assert (
        c.post(
            "/api/v1/auth/login",
            json={"email": "missing@example.com", "password": "wrong"},
        ).status_code
        == 401
    )
    assert c.post("/api/v1/auth/login", content="x" * 65537).status_code == 413
    for _ in range(20):
        store.allow_login("ip:testclient")
    assert (
        c.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": PASSWORD},
        ).status_code
        == 429
    )


def test_validation_never_echoes_credentials(setup):
    _, app, _ = setup
    c = TestClient(app, headers={"X-App-Request": "1"})
    secret = "private-password-" * 30
    response = c.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": secret}
    )
    assert response.status_code == 422
    assert secret not in response.text


def test_concurrent_invitation_acceptance_is_atomic(setup):
    from concurrent.futures import ThreadPoolExecutor

    store, app, ids = setup
    admin = client(app, "admin@example.com")
    created = admin.post(
        "/api/v1/workspace/invitations",
        json={"invited_email": "other@example.com", "role": "viewer"},
    ).json()
    token = created["invitation_token"]

    def accept_once():
        c = client(app, "other@example.com")
        return c.post(
            "/api/v1/onboarding/invitations/accept",
            json={
                "invitation_token": token,
                "accept_terms": True,
                "accept_privacy": True,
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: accept_once(), range(2))) == [200, 404]
    with store.connection() as db:
        assert (
            db.execute("SELECT count(*) FROM legal_acceptances").fetchone()["count"]
            == 1
        )


def test_operator_reset_revokes_sessions_and_preserves_memberships(setup, monkeypatch):
    import sys
    from app_core import cli

    store, app, ids = setup
    c = client(app, "admin@example.com")
    monkeypatch.setenv("DATABASE_URL", store.database_url)
    monkeypatch.setattr(
        sys, "argv", ["cli", "reset-password", "--email", "admin@example.com"]
    )
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "replacement-password")
    cli.main()
    assert c.get("/api/v1/me").status_code == 401
    assert len(store.list_active_global_access(ids["admin@example.com"])) == 2
    assert (
        c.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "replacement-password"},
        ).status_code
        == 200
    )
