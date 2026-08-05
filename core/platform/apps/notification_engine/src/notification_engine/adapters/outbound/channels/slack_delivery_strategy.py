import logging
from typing import Any

logger = logging.getLogger(__name__)


class SlackDeliveryStrategy:
    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None:
        logger.info(f"[SLACK] Delivering to tenant {tenant_id}. Body: {content}")
