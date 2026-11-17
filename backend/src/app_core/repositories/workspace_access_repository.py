"""Persistence contract and in-memory implementation for workspace access."""

from __future__ import annotations

from typing import Protocol

from app_core.domain.models import WorkspaceAccess


class WorkspaceAccessRepository(Protocol):
    def get_active_access(
        self, identity_tenant_id: str, identity_user_id: str
    ) -> WorkspaceAccess | None: ...
    def list_active_global_access(
        self, subject: str
    ) -> tuple[WorkspaceAccess, ...]: ...
    def get_active_global_access(
        self, subject: str, workspace_slug: str | None
    ) -> WorkspaceAccess | None: ...


class InMemoryWorkspaceAccessRepository:
    def __init__(self, memberships: tuple[WorkspaceAccess, ...]) -> None:
        self._memberships = memberships

    def get_active_access(
        self, identity_tenant_id: str, identity_user_id: str
    ) -> WorkspaceAccess | None:
        return next(
            (
                membership
                for membership in self._memberships
                if membership.workspace.id == identity_tenant_id
                and membership.user_id == identity_user_id
            ),
            None,
        )

    def list_active_global_access(self, subject: str) -> tuple[WorkspaceAccess, ...]:
        return tuple(
            membership
            for membership in self._memberships
            if membership.user_id == subject
        )

    def get_active_global_access(
        self, subject: str, workspace_slug: str | None
    ) -> WorkspaceAccess | None:
        memberships = self.list_active_global_access(subject)
        if workspace_slug is not None:
            normalized_slug = workspace_slug.strip().lower()
            memberships = tuple(
                membership
                for membership in memberships
                if membership.workspace_slug == normalized_slug
            )
        return memberships[0] if len(memberships) == 1 else None
