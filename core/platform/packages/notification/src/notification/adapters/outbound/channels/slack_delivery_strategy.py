from collections.abc import Mapping
from typing import Any, Protocol

import structlog

logger = structlog.get_logger(__name__)


class SlackIntegrationPort(Protocol):
    """Port for Slack integration."""

    async def send_message(
        self, tenant_id: str, content: str, subject: str | None, data: Mapping[str, Any]
    ) -> None: ...


class DeliveryError(Exception):
    """Raised when message delivery fails."""


class SlackDeliveryStrategy:
    def __init__(self, slack_integration: SlackIntegrationPort | None = None):
        self.slack_integration = slack_integration

    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: Mapping[str, Any]
    ) -> None:
        if self.slack_integration is None:
            raise DeliveryError("Slack integration not configured")

        logger.info(
            "slack_message_delivering",
            tenant_id=tenant_id,
        )
        await self.slack_integration.send_message(tenant_id, content, subject, data)
