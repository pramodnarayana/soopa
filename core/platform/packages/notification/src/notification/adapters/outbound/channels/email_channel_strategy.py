from typing import Protocol

import structlog
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


class EmailProviderPort(Protocol):
    """Port for email delivery integration."""

    async def send_email(
        self, tenant_id: str, content: str, subject: str | None, data: JsonDict
    ) -> None: ...


class DeliveryError(Exception):
    """Raised when message delivery fails."""


class EmailChannelStrategy:
    def __init__(self, email_provider: EmailProviderPort | None = None):
        self.email_provider = email_provider

    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: JsonDict
    ) -> None:
        if self.email_provider is None:
            raise DeliveryError("Email provider not configured")

        logger.info(
            "email_delivering",
            tenant_id=tenant_id,
        )
        await self.email_provider.send_email(tenant_id, content, subject, data)
