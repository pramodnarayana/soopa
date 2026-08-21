from collections.abc import Sequence

import structlog

from ucp.domain.models.webhook import WebhookDomainModel
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class ListWebhooksUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(self, tenant_id: str) -> Sequence[WebhookDomainModel]:
        logger.info("list_webhooks.started", tenant_id=tenant_id)

        async with self.uow:
            webhooks = await self.uow.webhook_repo.list_webhooks(tenant_id=tenant_id)

            logger.info(
                "list_webhooks.completed",
                tenant_id=tenant_id,
                count=len(webhooks),
            )
            return webhooks
