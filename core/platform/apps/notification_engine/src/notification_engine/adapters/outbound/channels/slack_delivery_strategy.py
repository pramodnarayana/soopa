import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class SlackIntegrationPort(Protocol):
    """Port for Slack integration."""

    async def send_message(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None: ...


class DeliveryError(Exception):
    """Raised when message delivery fails."""


class SlackDeliveryStrategy:
    def __init__(self, slack_integration: SlackIntegrationPort | None = None):
        self.slack_integration = slack_integration

    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None:
        if self.slack_integration is None:
            raise DeliveryError("Slack integration not configured")

        logger.info(f"[SLACK] Delivering to tenant {tenant_id}. Body: {content}")
        await self.slack_integration.send_message(tenant_id, content, subject, data)
