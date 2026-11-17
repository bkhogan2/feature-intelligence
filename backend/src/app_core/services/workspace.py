from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app_core.domain.models import WorkspaceSummary

WORKSPACE_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$")


@dataclass(frozen=True, slots=True)
class WorkspaceRecord:
    workspace_id: UUID
    workspace_slug: str
    identity_tenant_id: str
    workspace_name: str
    logo_url: str | None
    theme_color: str
    status: str = "active"


class WorkspaceRepository(Protocol):
    def resolve(self, workspace_slug: str) -> WorkspaceRecord | None: ...


class WorkspaceUnavailableError(Exception):
    """The requested public workspace workspace is unavailable."""


class InMemoryWorkspaceRepository:
    def __init__(self, workspaces: tuple[WorkspaceRecord, ...] = ()) -> None:
        self._workspaces = {
            workspace.workspace_slug: workspace for workspace in workspaces
        }

    def resolve(self, workspace_slug: str) -> WorkspaceRecord | None:
        workspace = self._workspaces.get(workspace_slug)
        return (
            workspace
            if workspace is not None and workspace.status == "active"
            else None
        )


class WorkspaceService:
    def __init__(self, repository: WorkspaceRepository) -> None:
        self._repository = repository

    def resolve(self, workspace_slug: str) -> WorkspaceSummary:
        normalized_slug = workspace_slug.strip().lower()
        if not WORKSPACE_SLUG_PATTERN.fullmatch(normalized_slug):
            raise WorkspaceUnavailableError
        workspace = self._repository.resolve(normalized_slug)
        if workspace is None:
            raise WorkspaceUnavailableError
        return WorkspaceSummary(
            workspace_slug=workspace.workspace_slug,
            workspace_name=workspace.workspace_name,
            logo_url=workspace.logo_url,
            theme_color=workspace.theme_color,
        )
