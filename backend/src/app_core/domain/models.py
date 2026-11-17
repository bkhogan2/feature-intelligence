from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")]
IdentityTenantId = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
]
WorkspaceSlug = Annotated[
    str,
    Field(
        min_length=3, max_length=63, pattern=r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$"
    ),
]
HttpsLogoUrl = Annotated[
    str,
    Field(min_length=9, max_length=2_048, pattern=r"^https://[^\s]+$"),
]
ThemeColor = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]
NonEmptyText = Annotated[str, Field(min_length=1, max_length=4_000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class WorkspaceRole(StrEnum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class WorkspaceMembershipStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class WorkspaceInvitationAdminStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class InvitationDeliveryStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    SENT = "sent"
    FAILED = "failed"


class AppearanceMode(StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class ColorPalette(StrEnum):
    WORKSPACE = "workspace"
    SLATE = "slate"
    BLUE = "blue"
    GREEN = "green"
    VIOLET = "violet"
    CUSTOM = "custom"


class BackgroundPalette(StrEnum):
    NEUTRAL = "neutral"
    WORKSPACE = "workspace"
    SLATE = "slate"
    BLUE = "blue"
    GREEN = "green"
    VIOLET = "violet"
    CUSTOM = "custom"


class InsetStyle(StrEnum):
    PLAIN = "plain"
    SOFT = "soft"
    TINTED = "tinted"


class UserPreferences(StrictModel):
    appearance_mode: AppearanceMode = AppearanceMode.SYSTEM
    color_palette: ColorPalette = ColorPalette.SLATE
    background_palette: BackgroundPalette = BackgroundPalette.NEUTRAL
    inset_style: InsetStyle = InsetStyle.PLAIN
    custom_accent_color: ThemeColor | None = None
    custom_background_color: ThemeColor | None = None


class UserPreferencesPatch(StrictModel):
    appearance_mode: AppearanceMode | None = None
    color_palette: ColorPalette | None = None
    background_palette: BackgroundPalette | None = None
    inset_style: InsetStyle | None = None
    custom_accent_color: ThemeColor | None = None
    custom_background_color: ThemeColor | None = None

    @model_validator(mode="after")
    def at_least_one_preference(self) -> UserPreferencesPatch:
        if (
            self.appearance_mode is None
            and self.color_palette is None
            and self.background_palette is None
            and self.inset_style is None
            and self.custom_accent_color is None
            and self.custom_background_color is None
        ):
            raise ValueError("at least one preference must be provided")
        return self


class Workspace(StrictModel):
    id: IdentityTenantId
    display_name: Annotated[str, Field(min_length=2, max_length=120)]


class WorkspaceAccess(StrictModel):
    workspace: Workspace
    user_id: Annotated[str, Field(min_length=1, max_length=128)]
    role: WorkspaceRole
    workspace_slug: WorkspaceSlug | None = None
    logo_url: HttpsLogoUrl | None = None
    theme_color: ThemeColor | None = None


class WorkspaceMembershipSummary(StrictModel):
    workspace_slug: WorkspaceSlug
    workspace_name: Annotated[str, Field(min_length=2, max_length=120)]
    role: WorkspaceRole
    logo_url: HttpsLogoUrl | None = None
    theme_color: ThemeColor


class WorkspaceSummary(StrictModel):
    workspace_slug: WorkspaceSlug
    workspace_name: Annotated[str, Field(min_length=2, max_length=120)]
    logo_url: HttpsLogoUrl | None = None
    theme_color: ThemeColor


class InvitationResolveRequest(StrictModel):
    invitation_token: Annotated[SecretStr, Field(min_length=32, max_length=256)]


class InvitationAcceptanceRequest(StrictModel):
    invitation_token: Annotated[SecretStr, Field(min_length=32, max_length=256)]
    accept_terms: Literal[True]
    accept_privacy: Literal[True]


class InvitationSummary(StrictModel):
    workspace_name: Annotated[str, Field(min_length=2, max_length=120)]
    invited_email: Annotated[str, Field(min_length=3, max_length=254)]
    role: WorkspaceRole
    expires_at: datetime
    terms_version: Annotated[str, Field(min_length=1, max_length=64)]
    privacy_version: Annotated[str, Field(min_length=1, max_length=64)]


class InvitationAcceptance(StrictModel):
    workspace_name: Annotated[str, Field(min_length=2, max_length=120)]
    role: WorkspaceRole
    status: Literal["active"] = "active"


class WorkspaceMemberSummary(StrictModel):
    membership_id: UUID
    email: Annotated[str, Field(min_length=3, max_length=254)] | None = None
    role: WorkspaceRole
    status: WorkspaceMembershipStatus
    is_current_user: bool
    created_at: datetime
    updated_at: datetime


class WorkspaceInvitationAdminSummary(StrictModel):
    invitation_id: UUID
    invited_email: Annotated[str, Field(min_length=3, max_length=254)]
    role: WorkspaceRole
    status: WorkspaceInvitationAdminStatus
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None


class WorkspaceInvitationCreateRequest(StrictModel):
    invited_email: Annotated[str, Field(min_length=3, max_length=254)]
    role: WorkspaceRole
    expires_in_days: Annotated[int, Field(ge=1, le=30)] = 7


class WorkspaceInvitationCreated(StrictModel):
    invitation: WorkspaceInvitationAdminSummary
    invitation_token: Annotated[str, Field(min_length=32, max_length=256)]
    delivery_status: InvitationDeliveryStatus = InvitationDeliveryStatus.NOT_CONFIGURED


class WorkspaceMemberPatch(StrictModel):
    role: WorkspaceRole | None = None
    status: WorkspaceMembershipStatus | None = None

    @model_validator(mode="after")
    def at_least_one_member_change(self) -> WorkspaceMemberPatch:
        if self.role is None and self.status is None:
            raise ValueError("at least one member change must be provided")
        return self


class FeedbackCreate(StrictModel):
    submission_key: UUID | None = None
    title: Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[^\x00]*$")]
    description: Annotated[
        str, Field(min_length=1, max_length=10_000, pattern=r"^[^\x00]*$")
    ]


class FeedbackSupport(StrictModel):
    support_count: int = Field(default=0, ge=0)
    supported_by_me: bool = False


class Feedback(FeedbackCreate, FeedbackSupport):
    approval_status: str | None = None
    approval_error: str | None = None
    priority: Literal["high", "medium", "low"] | None = None
    archived_from_status: (
        Literal["new", "needs_clarification", "triaged", "rejected"] | None
    ) = None
    status: Literal["new", "needs_clarification", "triaged", "rejected", "archived"] = (
        "new"
    )
    id: UUID
    workspace_id: str
    submitted_by: str
    submitter_name: str | None = None
    created_at: datetime


class FeedbackPage(StrictModel):
    items: list[Feedback]
    has_more: bool
