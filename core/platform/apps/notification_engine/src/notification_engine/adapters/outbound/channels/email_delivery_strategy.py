import logging
from typing import Any

logger = logging.getLogger(__name__)


class EmailDeliveryStrategy:
    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None:
        logger.info(
            f"[EMAIL] Delivering to tenant {tenant_id}. Subject: {subject}. Body: {content}"
        )
