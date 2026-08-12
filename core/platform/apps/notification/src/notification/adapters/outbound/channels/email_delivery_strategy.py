import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class EmailProviderPort(Protocol):
    """Port for email delivery integration."""

    async def send_email(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None: ...


class DeliveryError(Exception):
    """Raised when message delivery fails."""


class EmailDeliveryStrategy:
    def __init__(self, email_provider: EmailProviderPort | None = None):
        self.email_provider = email_provider

    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None:
        if self.email_provider is None:
            raise DeliveryError("Email provider not configured")

        logger.info(
            f"[EMAIL] Delivering to tenant {tenant_id}. Subject: {subject}. Body: {content}"
        )
        await self.email_provider.send_email(tenant_id, content, subject, data)
