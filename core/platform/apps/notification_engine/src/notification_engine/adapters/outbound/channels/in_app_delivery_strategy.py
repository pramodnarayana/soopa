import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class InAppPersistencePort(Protocol):
    """Port for in-app notification persistence."""

    async def save_notification(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None: ...


class DeliveryError(Exception):
    """Raised when message delivery fails."""

    pass


class InAppDeliveryStrategy:
    def __init__(self, persistence: InAppPersistencePort | None = None):
        self.persistence = persistence

    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None:
        if self.persistence is None:
            raise DeliveryError("In-app persistence not configured")

        logger.info(f"[IN_APP] Delivering to tenant {tenant_id}. Body: {content}")
        await self.persistence.save_notification(tenant_id, content, subject, data)
