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
        bound_logger = logger.bind(tenant_id=tenant_id)
        bound_logger.info(
            "ucp_webhook_creation_started",
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

            bound_logger.debug(
                "ucp_webhook_aggregate_created",
                webhook_id=webhook.id,
                webhook_name=webhook.name,
                webhook_url=webhook.url,
                has_auth_header=auth_header_vault_ref is not None,
                domain_events_queued=len(webhook.domain_events),
            )

            await self.uow.webhook_repo.save(webhook, idempotency_key=idempotency_key)

            bound_logger.info(
                "ucp_webhook_outbox_flushed",
                webhook_id=webhook.id,
            )

            await self.uow.commit()

            bound_logger.info(
                "ucp_webhook_created",
                webhook_id=webhook.id,
            )
            return webhook
