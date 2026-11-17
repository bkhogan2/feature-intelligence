from datetime import datetime
from typing import Protocol
from app_core.domain.models import InvitationDeliveryStatus


class InvitationEmailSender(Protocol):
    def send_invitation(
        self,
        *,
        recipient_email: str,
        workspace_name: str,
        expires_at: datetime,
        raw_token: str,
    ) -> InvitationDeliveryStatus: ...


class DisabledInvitationEmailSender:
    def send_invitation(
        self,
        *,
        recipient_email: str,
        workspace_name: str,
        expires_at: datetime,
        raw_token: str,
    ) -> InvitationDeliveryStatus:
        del recipient_email, workspace_name, expires_at, raw_token
        return InvitationDeliveryStatus.NOT_CONFIGURED
