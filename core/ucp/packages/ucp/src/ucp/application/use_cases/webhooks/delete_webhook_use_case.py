import structlog

from ucp.domain.events.webhook_events import WebhookDeletedEvent
from ucp.ports.uow import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DeleteWebhookUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self, tenant_id: str, webhook_id: str, idempotency_key: str | None = None
    ) -> None:
        bound_logger = logger.bind(tenant_id=tenant_id, webhook_id=webhook_id)
        bound_logger.info("delete_webhook.started", idempotency_key=idempotency_key)

        async with self.uow:
            webhook = await self.uow.webhook_repo.find_by_id(tenant_id, webhook_id)
            if not webhook:
                bound_logger.error("delete_webhook.not_found")
                raise ValueError(f"Webhook {webhook_id} not found")

            # Emitting deleted event before we actually delete the record
            webhook.add_domain_event(
                WebhookDeletedEvent(tenant_id=tenant_id, webhook_id=webhook_id)
            )

            await self.uow.webhook_repo.delete_webhook(
                tenant_id=tenant_id, webhook_id=webhook_id, idempotency_key=idempotency_key
            )
            await self.uow.commit()

            bound_logger.info("delete_webhook.completed")
