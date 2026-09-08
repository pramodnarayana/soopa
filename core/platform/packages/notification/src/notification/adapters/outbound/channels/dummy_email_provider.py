import structlog
from seedwork.domain.types import JsonDict

from .email_channel_strategy import EmailProviderPort

logger = structlog.get_logger(__name__)


class DummyEmailProvider(EmailProviderPort):
    async def send_email(
        self, tenant_id: str, content: str, subject: str | None, data: JsonDict
    ) -> None:
        logger.info("dummy_email_sent", tenant_id=tenant_id)
