import structlog

from ucp.domain.models.webhook import WebhookDomainModel
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class UpdateWebhookUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self,
        tenant_id: str,
        webhook_id: str,
        name: str | None,
        url: str | None,
        active: bool | None,
        idempotency_key: str | None = None,
    ) -> WebhookDomainModel:
        bound_logger = logger.bind(tenant_id=tenant_id, webhook_id=webhook_id)
        bound_logger.info("update_webhook.started", idempotency_key=idempotency_key)

        async with self.uow:
            webhook = await self.uow.webhook_repo.find_by_id(tenant_id, webhook_id)
            if not webhook:
                bound_logger.error("update_webhook.not_found")
                raise ValueError(f"Webhook {webhook_id} not found")

            webhook.update(name=name, url=url, active=active)

            await self.uow.webhook_repo.save(webhook, idempotency_key=idempotency_key)
            await self.uow.commit()

            bound_logger.info("update_webhook.completed")
            return webhook
