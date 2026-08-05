import logging
from typing import Any

logger = logging.getLogger(__name__)


class InAppDeliveryStrategy:
    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None:
        logger.info(f"[IN_APP] Delivering to tenant {tenant_id}. Body: {content}")
