from __future__ import annotations
import hashlib
import os
from collections.abc import Mapping
from typing import Any
import firebase_admin
from firebase_admin import App, auth, exceptions
from app_core.auth.identity import (
    VerifiedIdentity,
    InvalidAuthenticationError,
    IdentityVerificationUnavailableError,
)


class FirebaseIdentityTokenVerifier:
    def __init__(self, project_id: str, firebase_app: App | None = None) -> None:
        if not project_id.strip():
            raise ValueError("project_id must not be blank")
        if os.getenv("FIREBASE_AUTH_EMULATOR_HOST"):
            raise RuntimeError(
                "The live Firebase adapter does not accept emulator configuration"
            )
        self._app = firebase_app or _firebase_app(project_id.strip())
        if self._app.options.get("projectId") != project_id.strip():
            raise ValueError(
                "Firebase Admin application project does not match configured project"
            )

    def verify(self, token: str) -> VerifiedIdentity:
        if not token.strip():
            raise InvalidAuthenticationError

        try:
            claims = auth.verify_id_token(token, app=self._app, check_revoked=True)
            if _optional_tenant_id_from_claims(claims) is not None:
                raise InvalidAuthenticationError
            subject = claims.get("uid") or claims.get("sub")
            if not isinstance(subject, str) or not subject:
                raise InvalidAuthenticationError
            email = claims.get("email")
            if not isinstance(email, str) or not email:
                email = None
            return VerifiedIdentity(
                subject=subject,
                email=email,
                email_verified=claims.get("email_verified") is True,
            )
        except InvalidAuthenticationError:
            raise
        except (
            auth.InvalidIdTokenError,
            auth.UserDisabledError,
            auth.UserNotFoundError,
            ValueError,
        ) as error:
            raise InvalidAuthenticationError from error
        except exceptions.FirebaseError as error:
            raise IdentityVerificationUnavailableError from error


def _firebase_app(project_id: str) -> App:
    digest = hashlib.sha256(project_id.encode()).hexdigest()[:12]
    app_name = f"app-starter-{digest}"
    try:
        return firebase_admin.get_app(app_name)
    except ValueError:
        return firebase_admin.initialize_app(
            options={"projectId": project_id},
            name=app_name,
        )


def _tenant_id_from_claims(claims: Mapping[str, Any]) -> str:
    firebase_claim = claims.get("firebase")
    if not isinstance(firebase_claim, Mapping):
        raise InvalidAuthenticationError
    tenant_id = firebase_claim.get("tenant")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise InvalidAuthenticationError
    return tenant_id


def _optional_tenant_id_from_claims(claims: Mapping[str, Any]) -> str | None:
    firebase_claim = claims.get("firebase")
    if not isinstance(firebase_claim, Mapping):
        return None
    tenant_id = firebase_claim.get("tenant")
    return tenant_id if isinstance(tenant_id, str) and tenant_id else None
