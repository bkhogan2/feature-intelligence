from __future__ import annotations

import hashlib
import secrets
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4


from app_core.auth.identity import Principal
from app_core.auth.invitation_email import (
    DisabledInvitationEmailSender,
    InvitationEmailSender,
)
from app_core.domain.models import (
    WorkspaceInvitationAdminStatus,
    WorkspaceInvitationAdminSummary,
    WorkspaceInvitationCreated,
    WorkspaceMembershipStatus,
    WorkspaceMemberSummary,
    WorkspaceRole,
    InvitationDeliveryStatus,
)


class WorkspaceAdminForbiddenError(Exception):
    """The caller is not an active administrator of the selected workspace."""


class WorkspaceAdminConflictError(Exception):
    """The requested invitation conflicts with an existing member or invitation."""


class WorkspaceAdminNotFoundError(Exception):
    """The selected workspace member or invitation was not found."""


class LastWorkspaceAdminError(Exception):
    """The change would leave the workspace without an active administrator."""


class SelfRemovalError(Exception):
    """An administrator attempted to remove their own workspace membership."""


class WorkspaceAdminRepository(Protocol):
    def list_members(
        self, actor_uid: str, tenant_id: str
    ) -> tuple[WorkspaceMemberSummary, ...]: ...

    def list_invitations(
        self, actor_uid: str, tenant_id: str
    ) -> tuple[WorkspaceInvitationAdminSummary, ...]: ...

    def create_invitation(
        self,
        *,
        actor_uid: str,
        tenant_id: str,
        invited_email: str,
        role: WorkspaceRole,
        token_digest: bytes,
        expires_at: datetime,
    ) -> WorkspaceInvitationAdminSummary: ...

    def revoke_invitation(
        self,
        *,
        actor_uid: str,
        tenant_id: str,
        invitation_id: UUID,
    ) -> WorkspaceInvitationAdminSummary: ...

    def update_member(
        self,
        *,
        actor_uid: str,
        tenant_id: str,
        membership_id: UUID,
        role: WorkspaceRole | None,
        status: WorkspaceMembershipStatus | None,
    ) -> WorkspaceMemberSummary: ...

    def remove_member(
        self,
        *,
        actor_uid: str,
        tenant_id: str,
        membership_id: UUID,
    ) -> None: ...


class InMemoryWorkspaceAdminRepository:
    def __init__(
        self,
        *,
        members: Mapping[str, tuple[WorkspaceMemberSummary, ...]] | None = None,
        invitations: Mapping[str, tuple[WorkspaceInvitationAdminSummary, ...]]
        | None = None,
        actor_admin_tenants: Mapping[str, frozenset[str]] | None = None,
    ) -> None:
        self._members = {key: list(value) for key, value in (members or {}).items()}
        self._invitations = {
            key: list(value) for key, value in (invitations or {}).items()
        }
        self._actor_admin_tenants = dict(actor_admin_tenants or {})
        self._lock = threading.Lock()

    def list_members(
        self, actor_uid: str, tenant_id: str
    ) -> tuple[WorkspaceMemberSummary, ...]:
        self._require_admin(actor_uid, tenant_id)
        with self._lock:
            return tuple(self._members.get(tenant_id, ()))

    def list_invitations(
        self, actor_uid: str, tenant_id: str
    ) -> tuple[WorkspaceInvitationAdminSummary, ...]:
        self._require_admin(actor_uid, tenant_id)
        with self._lock:
            return tuple(self._invitations.get(tenant_id, ()))

    def create_invitation(
        self,
        *,
        actor_uid: str,
        tenant_id: str,
        invited_email: str,
        role: WorkspaceRole,
        token_digest: bytes,
        expires_at: datetime,
    ) -> WorkspaceInvitationAdminSummary:
        del token_digest
        self._require_admin(actor_uid, tenant_id)
        now = datetime.now(UTC)
        with self._lock:
            if any(
                member.email == invited_email
                for member in self._members.get(tenant_id, ())
            ) or any(
                invitation.invited_email == invited_email
                and invitation.status == WorkspaceInvitationAdminStatus.PENDING
                and invitation.expires_at > now
                for invitation in self._invitations.get(tenant_id, ())
            ):
                raise WorkspaceAdminConflictError
            invitation = WorkspaceInvitationAdminSummary(
                invitation_id=uuid4(),
                invited_email=invited_email,
                role=role,
                status=WorkspaceInvitationAdminStatus.PENDING,
                created_at=now,
                expires_at=expires_at,
            )
            self._invitations.setdefault(tenant_id, []).append(invitation)
            return invitation

    def revoke_invitation(
        self,
        *,
        actor_uid: str,
        tenant_id: str,
        invitation_id: UUID,
    ) -> WorkspaceInvitationAdminSummary:
        self._require_admin(actor_uid, tenant_id)
        with self._lock:
            invitations = self._invitations.get(tenant_id, [])
            for index, invitation in enumerate(invitations):
                if (
                    invitation.invitation_id == invitation_id
                    and invitation.status == WorkspaceInvitationAdminStatus.PENDING
                ):
                    updated = invitation.model_copy(
                        update={
                            "status": WorkspaceInvitationAdminStatus.REVOKED,
                            "revoked_at": datetime.now(UTC),
                        }
                    )
                    invitations[index] = updated
                    return updated
        raise WorkspaceAdminNotFoundError

    def update_member(
        self,
        *,
        actor_uid: str,
        tenant_id: str,
        membership_id: UUID,
        role: WorkspaceRole | None,
        status: WorkspaceMembershipStatus | None,
    ) -> WorkspaceMemberSummary:
        self._require_admin(actor_uid, tenant_id)
        with self._lock:
            members = self._members.get(tenant_id, [])
            for index, member in enumerate(members):
                if member.membership_id != membership_id:
                    continue
                resulting_role = role or member.role
                resulting_status = status or member.status
                if (
                    member.role == WorkspaceRole.ADMIN
                    and member.status == WorkspaceMembershipStatus.ACTIVE
                    and (
                        resulting_role != WorkspaceRole.ADMIN
                        or resulting_status != WorkspaceMembershipStatus.ACTIVE
                    )
                    and not any(
                        candidate.membership_id != membership_id
                        and candidate.role == WorkspaceRole.ADMIN
                        and candidate.status == WorkspaceMembershipStatus.ACTIVE
                        for candidate in members
                    )
                ):
                    raise LastWorkspaceAdminError
                updated = member.model_copy(
                    update={
                        "role": resulting_role,
                        "status": resulting_status,
                        "updated_at": datetime.now(UTC),
                    }
                )
                members[index] = updated
                return updated
        raise WorkspaceAdminNotFoundError

    def remove_member(
        self,
        *,
        actor_uid: str,
        tenant_id: str,
        membership_id: UUID,
    ) -> None:
        self._require_admin(actor_uid, tenant_id)
        with self._lock:
            members = self._members.get(tenant_id, [])
            for index, member in enumerate(members):
                if member.membership_id != membership_id:
                    continue
                if member.is_current_user:
                    raise SelfRemovalError
                if (
                    member.role == WorkspaceRole.ADMIN
                    and member.status == WorkspaceMembershipStatus.ACTIVE
                    and not any(
                        candidate.membership_id != membership_id
                        and candidate.role == WorkspaceRole.ADMIN
                        and candidate.status == WorkspaceMembershipStatus.ACTIVE
                        for candidate in members
                    )
                ):
                    raise LastWorkspaceAdminError
                members.pop(index)
                return
        raise WorkspaceAdminNotFoundError

    def _require_admin(self, actor_uid: str, tenant_id: str) -> None:
        if tenant_id not in self._actor_admin_tenants.get(actor_uid, frozenset()):
            raise WorkspaceAdminForbiddenError


class WorkspaceAdminService:
    def __init__(
        self,
        repository: WorkspaceAdminRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
        invitation_email_sender: InvitationEmailSender | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._invitation_email_sender = (
            invitation_email_sender or DisabledInvitationEmailSender()
        )

    def list_members(self, principal: Principal) -> tuple[WorkspaceMemberSummary, ...]:
        self._require_admin(principal)
        return self._repository.list_members(principal.subject, principal.tenant_id)

    def list_invitations(
        self, principal: Principal
    ) -> tuple[WorkspaceInvitationAdminSummary, ...]:
        self._require_admin(principal)
        return self._repository.list_invitations(principal.subject, principal.tenant_id)

    def create_invitation(
        self,
        principal: Principal,
        invited_email: str,
        role: WorkspaceRole,
        expires_in_days: int,
    ) -> WorkspaceInvitationCreated:
        self._require_admin(principal)
        if expires_in_days < 1 or expires_in_days > 30:
            raise ValueError("expires_in_days must be between 1 and 30")
        normalized_email = _normalize_email(invited_email)
        raw_token = self._token_factory()
        if len(raw_token) < 32 or len(raw_token) > 256:
            raise RuntimeError("token factory returned an invalid token length")
        invitation = self._repository.create_invitation(
            actor_uid=principal.subject,
            tenant_id=principal.tenant_id,
            invited_email=normalized_email,
            role=role,
            token_digest=hashlib.sha256(raw_token.encode("utf-8")).digest(),
            expires_at=self._clock() + timedelta(days=expires_in_days),
        )
        try:
            delivery_status = self._invitation_email_sender.send_invitation(
                recipient_email=normalized_email,
                workspace_name=principal.workspace.display_name,
                expires_at=invitation.expires_at,
                raw_token=raw_token,
            )
        except Exception:
            # Invitation creation has already committed. Preserve the one-time
            # manual-link fallback rather than turning a delivery fault into a
            # misleading retry that conflicts with the pending invitation.
            delivery_status = InvitationDeliveryStatus.FAILED
        return WorkspaceInvitationCreated(
            invitation=invitation,
            invitation_token=raw_token,
            delivery_status=delivery_status,
        )

    def revoke_invitation(
        self, principal: Principal, invitation_id: UUID
    ) -> WorkspaceInvitationAdminSummary:
        self._require_admin(principal)
        return self._repository.revoke_invitation(
            actor_uid=principal.subject,
            tenant_id=principal.tenant_id,
            invitation_id=invitation_id,
        )

    def update_member(
        self,
        principal: Principal,
        membership_id: UUID,
        role: WorkspaceRole | None,
        status: WorkspaceMembershipStatus | None,
    ) -> WorkspaceMemberSummary:
        self._require_admin(principal)
        return self._repository.update_member(
            actor_uid=principal.subject,
            tenant_id=principal.tenant_id,
            membership_id=membership_id,
            role=role,
            status=status,
        )

    def remove_member(self, principal: Principal, membership_id: UUID) -> None:
        self._require_admin(principal)
        self._repository.remove_member(
            actor_uid=principal.subject,
            tenant_id=principal.tenant_id,
            membership_id=membership_id,
        )

    @staticmethod
    def _require_admin(principal: Principal) -> None:
        if principal.role != WorkspaceRole.ADMIN:
            raise WorkspaceAdminForbiddenError


def _normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if (
        len(normalized) > 254
        or normalized.count("@") != 1
        or any(character.isspace() for character in normalized)
    ):
        raise ValueError("invited_email is invalid")
    local_part, domain = normalized.rsplit("@", 1)
    if not local_part or not domain or "." not in domain:
        raise ValueError("invited_email is invalid")
    return normalized
