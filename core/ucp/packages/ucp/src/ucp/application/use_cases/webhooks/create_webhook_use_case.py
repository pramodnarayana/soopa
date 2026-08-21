import structlog

from ucp.domain.models.webhook import WebhookDomainModel
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class CreateWebhookUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self,
        tenant_id: str,
        name: str,
        url: str,
        auth_header_vault_ref: str | None,
        idempotency_key: str | None = None,
    ) -> WebhookDomainModel:
        logger.info(
            "create_webhook.started",
            tenant_id=tenant_id,
            webhook_name=name,
            idempotency_key=idempotency_key,
        )

        async with self.uow:
            webhook = WebhookDomainModel.create(
                tenant_id=tenant_id,
                name=name,
                url=url,
                auth_header_vault_ref=auth_header_vault_ref,
            )

            await self.uow.webhook_repo.save(webhook, idempotency_key=idempotency_key)
            await self.uow.commit()

            logger.info(
                "create_webhook.completed",
                tenant_id=tenant_id,
                webhook_id=webhook.id,
            )
            return webhook
