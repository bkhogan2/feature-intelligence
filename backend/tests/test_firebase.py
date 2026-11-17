"""Firebase adapter contracts; no live users or emails."""

from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

auth = pytest.importorskip("firebase_admin.auth")
exceptions = pytest.importorskip("firebase_admin.exceptions")
from app_core.auth.google import FirebaseIdentityTokenVerifier  # noqa: E402
from app_core.auth.identity import (  # noqa: E402
    InvalidAuthenticationError,
    IdentityVerificationUnavailableError,
    VerifiedIdentity,
)
from app_core.main import create_app  # noqa: E402


def verifier():
    return FirebaseIdentityTokenVerifier(
        "starter-test",
        firebase_app=SimpleNamespace(options={"projectId": "starter-test"}),
    )


def test_verifier_checks_revocation_and_project(monkeypatch):
    calls = []

    def verify(token, **kwargs):
        calls.append(kwargs)
        return {
            "uid": "firebase-user",
            "email": "owner@example.com",
            "email_verified": True,
        }

    monkeypatch.setattr(auth, "verify_id_token", verify)
    assert verifier().verify("token").email_verified
    assert calls[0]["check_revoked"] is True
    assert calls[0]["app"].options["projectId"] == "starter-test"


@pytest.mark.parametrize(
    "error",
    [
        auth.InvalidIdTokenError("invalid"),
        auth.RevokedIdTokenError("revoked"),
        auth.UserDisabledError("disabled"),
    ],
)
def test_bad_tokens_rejected(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(auth, "verify_id_token", fail)
    with pytest.raises(InvalidAuthenticationError):
        verifier().verify("bad-token")


def test_transient_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise exceptions.UnavailableError("unavailable")

    monkeypatch.setattr(auth, "verify_id_token", fail)
    with pytest.raises(IdentityVerificationUnavailableError):
        verifier().verify("token")


def test_wrong_tenant_project_and_emulator_rejected(monkeypatch):
    monkeypatch.setattr(
        auth,
        "verify_id_token",
        lambda *args, **kwargs: {"uid": "user", "firebase": {"tenant": "other"}},
    )
    with pytest.raises(InvalidAuthenticationError):
        verifier().verify("tenant-token")
    with pytest.raises(ValueError, match="does not match"):
        FirebaseIdentityTokenVerifier(
            "starter-test", firebase_app=SimpleNamespace(options={"projectId": "other"})
        )
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "localhost:9099")
    with pytest.raises(RuntimeError, match="emulator"):
        verifier()


def test_firebase_does_not_accept_local_cookie_or_password(pg_store, monkeypatch):
    store, _ = pg_store
    uid = store.provision("owner@example.com", None, "alpha", "Alpha")
    monkeypatch.setenv("AUTH_PROVIDER", "firebase")
    monkeypatch.setenv("GOOGLE_PROJECT_ID", "starter-test")

    class Verified:
        def verify(self, token):
            return VerifiedIdentity(
                subject=uid, email="owner@example.com", email_verified=True
            )

    c = TestClient(
        create_app(store, verifier=Verified()), headers={"X-App-Request": "1"}
    )
    c.cookies.set("app_session", store.new_session(uid))
    assert c.get("/api/v1/auth/config").json() == {
        "provider": "firebase",
        "projectId": "starter-test",
    }
    assert c.get("/api/v1/me").status_code == 401
    assert (
        c.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "unused"},
        ).status_code
        == 404
    )
    c.headers["Authorization"] = "Bearer verified-token"
    assert c.get("/api/v1/me/workspaces").json()[0]["workspace_slug"] == "alpha"


@pytest.mark.parametrize("verified", [False, True])
def test_unverified_or_different_uid_cannot_claim_existing_email(
    pg_store, monkeypatch, verified
):
    store, _ = pg_store
    store.provision("owner@example.com", None, "alpha", "Alpha")
    monkeypatch.setenv("AUTH_PROVIDER", "firebase")
    monkeypatch.setenv("GOOGLE_PROJECT_ID", "starter-test")

    class Other:
        def verify(self, token):
            return VerifiedIdentity(
                subject="other-uid", email="owner@example.com", email_verified=verified
            )

    c = TestClient(
        create_app(store, verifier=Other()), headers={"Authorization": "Bearer token"}
    )
    assert c.get("/api/v1/me").status_code == 401


def test_new_verified_identity_does_not_get_workspace_access(pg_store, monkeypatch):
    store, _ = pg_store
    monkeypatch.setenv("AUTH_PROVIDER", "firebase")
    monkeypatch.setenv("GOOGLE_PROJECT_ID", "starter-test")

    class Verified:
        def verify(self, token):
            return VerifiedIdentity(
                subject="new-firebase-user",
                email="new@example.com",
                email_verified=True,
            )

    c = TestClient(
        create_app(store, verifier=Verified()),
        headers={"Authorization": "Bearer token"},
    )
    assert c.get("/api/v1/me").status_code == 200
    assert c.get("/api/v1/me/workspaces").json() == []
    assert c.get("/api/v1/records", headers={"X-Workspace": "alpha"}).status_code == 404


def test_firebase_operator_cli_requires_provider_subject(monkeypatch):
    import sys
    from app_core import cli

    monkeypatch.setenv("AUTH_PROVIDER", "firebase")
    monkeypatch.setattr(sys, "argv", ["cli", "demo"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
