from collections.abc import Mapping
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class DeliveryError(Exception):
    """Raised when message delivery fails."""


class InAppDeliveryStrategy:
    def __init__(self) -> None:
        pass

    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: Mapping[str, Any]
    ) -> None:

        logger.info(
            "in_app_notification_delivering",
            tenant_id=tenant_id,
        )
        # In-app notification is already saved to DB in Stage 2 (Compiler).
        # In the future, this is where we'd push to a WebSocket server or SSE.
