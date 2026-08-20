from typing import Any

import structlog

logger = structlog.get_logger(__name__)


from notification.ports.in_app_notification_persistence_port import InAppNotificationPersistencePort


class DeliveryError(Exception):
    """Raised when message delivery fails."""


class InAppDeliveryStrategy:
    def __init__(self, persistence: InAppNotificationPersistencePort | None = None):
        self.persistence = persistence

    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None:
        if self.persistence is None:
            raise DeliveryError("In-app persistence not configured")

        logger.info(
            "[IN_APP] Delivering to tenant {tenant_id}. Body: {content}",
            tenant_id=tenant_id,
            content=content,
        )
        await self.persistence.save_notification(tenant_id, content, subject, data)
