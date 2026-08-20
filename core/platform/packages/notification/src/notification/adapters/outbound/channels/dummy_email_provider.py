from collections.abc import Mapping
from typing import Any

import structlog

from .email_delivery_strategy import EmailProviderPort

logger = structlog.get_logger(__name__)


class DummyEmailProvider(EmailProviderPort):
    async def send_email(
        self, tenant_id: str, content: str, subject: str | None, data: Mapping[str, Any]
    ) -> None:
        logger.info("dummy_email_sent", tenant_id=tenant_id)
