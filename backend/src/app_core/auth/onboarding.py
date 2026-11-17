from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app_core.auth.identity import VerifiedIdentity
from app_core.domain.models import (
    WorkspaceRole,
    InvitationAcceptance,
    InvitationSummary,
)


@dataclass(frozen=True, slots=True)
class InvitationRecord:
    id: UUID
    workspace_id: UUID
    identity_tenant_id: str
    workspace_name: str
    invited_email: str
    role: WorkspaceRole
    expires_at: datetime
    token_digest: bytes
    status: str = "pending"
    accepted_by_identity_user_id: str | None = None
    accepted_at: datetime | None = None


class InvitationRepository(Protocol):
    def resolve(
        self, token_digest: bytes, now: datetime
    ) -> InvitationRecord | None: ...

    def accept(
        self,
        *,
        invitation: InvitationRecord,
        identity: VerifiedIdentity,
        terms_version: str,
        privacy_version: str,
        accepted_at: datetime,
    ) -> bool: ...


class InvitationUnavailableError(Exception):
    """The invitation is missing, expired, revoked, accepted, or lost a race."""


class InvitationIdentityMismatchError(Exception):
    """The verified identity is not permitted to accept the invitation."""


class InMemoryInvitationRepository:
    def __init__(self, invitations: tuple[InvitationRecord, ...] = ()) -> None:
        self._invitations = {invitation.id: invitation for invitation in invitations}
        self._legal_acceptances: list[tuple[UUID, str, str, str]] = []
        self._lock = threading.Lock()

    @property
    def legal_acceptances(self) -> tuple[tuple[UUID, str, str, str], ...]:
        return tuple(self._legal_acceptances)

    def resolve(self, token_digest: bytes, now: datetime) -> InvitationRecord | None:
        with self._lock:
            return next(
                (
                    invitation
                    for invitation in self._invitations.values()
                    if invitation.token_digest == token_digest
                    and invitation.status == "pending"
                    and invitation.expires_at > now
                ),
                None,
            )

    def accept(
        self,
        *,
        invitation: InvitationRecord,
        identity: VerifiedIdentity,
        terms_version: str,
        privacy_version: str,
        accepted_at: datetime,
    ) -> bool:
        with self._lock:
            current = self._invitations.get(invitation.id)
            if (
                current is None
                or current.status != "pending"
                or current.expires_at <= accepted_at
                or current.token_digest != invitation.token_digest
            ):
                return False
            self._invitations[invitation.id] = replace(
                current,
                status="accepted",
                accepted_by_identity_user_id=identity.subject,
                accepted_at=accepted_at,
            )
            self._legal_acceptances.extend(
                (
                    (invitation.id, identity.subject, "terms", terms_version),
                    (invitation.id, identity.subject, "privacy", privacy_version),
                )
            )
            return True


class OnboardingService:
    def __init__(
        self,
        repository: InvitationRepository,
        *,
        terms_version: str,
        privacy_version: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not terms_version.strip() or not privacy_version.strip():
            raise ValueError("policy versions must not be blank")
        self._repository = repository
        self._terms_version = terms_version.strip()
        self._privacy_version = privacy_version.strip()
        self._clock = clock or (lambda: datetime.now(UTC))

    def resolve(self, raw_token: str) -> InvitationSummary:
        invitation = self._repository.resolve(_token_digest(raw_token), self._clock())
        if invitation is None:
            raise InvitationUnavailableError
        return InvitationSummary(
            workspace_name=invitation.workspace_name,
            invited_email=invitation.invited_email,
            role=invitation.role,
            expires_at=invitation.expires_at,
            terms_version=self._terms_version,
            privacy_version=self._privacy_version,
        )

    def accept(
        self, raw_token: str, identity: VerifiedIdentity
    ) -> InvitationAcceptance:
        now = self._clock()
        invitation = self._repository.resolve(_token_digest(raw_token), now)
        if invitation is None:
            raise InvitationUnavailableError
        if not identity.email_verified or identity.email is None:
            raise InvitationIdentityMismatchError
        if (
            identity.tenant_id is not None
            and identity.tenant_id != invitation.identity_tenant_id
        ):
            raise InvitationIdentityMismatchError
        if _normalize_email(identity.email) != invitation.invited_email:
            raise InvitationIdentityMismatchError
        accepted = self._repository.accept(
            invitation=invitation,
            identity=identity,
            terms_version=self._terms_version,
            privacy_version=self._privacy_version,
            accepted_at=now,
        )
        if not accepted:
            raise InvitationUnavailableError
        return InvitationAcceptance(
            workspace_name=invitation.workspace_name, role=invitation.role
        )


def _token_digest(raw_token: str) -> bytes:
    token = raw_token.strip()
    if len(token) < 32 or len(token) > 256:
        raise InvitationUnavailableError
    return hashlib.sha256(token.encode("utf-8")).digest()


def _normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if (
        len(normalized) > 254
        or normalized.count("@") != 1
        or any(character.isspace() for character in normalized)
    ):
        raise InvitationIdentityMismatchError
    local_part, domain = normalized.rsplit("@", 1)
    if not local_part or not domain or "." not in domain:
        raise InvitationIdentityMismatchError
    return normalized
