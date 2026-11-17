from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from app_core.domain.models import Workspace, WorkspaceAccess, WorkspaceRole
from app_core.repositories.workspace_access_repository import WorkspaceAccessRepository


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    workspace: Workspace
    role: WorkspaceRole

    @property
    def tenant_id(self) -> str:
        return self.workspace.id


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    subject: str
    tenant_id: str | None = None
    email: str | None = None
    email_verified: bool = False


class IdentityTokenVerifier(Protocol):
    def verify(self, token: str) -> VerifiedIdentity: ...


class AuthenticationBackend(Protocol):
    def verify_identity(self, authorization: str | None) -> VerifiedIdentity: ...

    def authenticate(
        self,
        authorization: str | None,
        demo_identity: str | None,
        workspace_slug: str | None = None,
    ) -> Principal: ...

    def list_memberships(
        self, authorization: str | None
    ) -> tuple[WorkspaceAccess, ...]: ...


class InvalidAuthenticationError(Exception):
    """The request did not contain valid authentication credentials."""


class MembershipRequiredError(Exception):
    """The verified identity has no active workspace membership."""


class IdentityVerificationUnavailableError(Exception):
    """Identity Platform verification is temporarily unavailable."""


class TokenAuthenticationBackend:
    def __init__(
        self,
        token_verifier: IdentityTokenVerifier,
        access_repository: WorkspaceAccessRepository,
    ) -> None:
        self._token_verifier = token_verifier
        self._access_repository = access_repository

    def verify_identity(self, authorization: str | None) -> VerifiedIdentity:
        return self._token_verifier.verify(_bearer_token(authorization))

    def authenticate(
        self,
        authorization: str | None,
        demo_identity: str | None,
        workspace_slug: str | None = None,
    ) -> Principal:
        del demo_identity
        identity = self.verify_identity(authorization)
        if identity.tenant_id is None:
            access = self._access_repository.get_active_global_access(
                identity.subject,
                workspace_slug,
            )
        else:
            access = self._access_repository.get_active_access(
                identity.tenant_id,
                identity.subject,
            )
        if access is None:
            raise MembershipRequiredError
        return _principal_from_access(access)

    def list_memberships(
        self, authorization: str | None
    ) -> tuple[WorkspaceAccess, ...]:
        identity = self.verify_identity(authorization)
        if identity.tenant_id is None:
            return self._access_repository.list_active_global_access(identity.subject)
        access = self._access_repository.get_active_access(
            identity.tenant_id, identity.subject
        )
        return (access,) if access is not None else ()


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise InvalidAuthenticationError
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise InvalidAuthenticationError
    return token.strip()


def _principal_from_access(access: WorkspaceAccess) -> Principal:
    return Principal(
        subject=access.user_id,
        workspace=access.workspace,
        role=access.role,
    )
