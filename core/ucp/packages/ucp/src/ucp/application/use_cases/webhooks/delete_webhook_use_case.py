import structlog

from ucp.domain.events import WebhookDeletedEvent
from ucp.domain.exceptions import ResourceNotFoundError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DeleteWebhookUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self,
        tenant_id: str,
        webhook_id: str,
        deleted_by: str,
        idempotency_key: str | None = None,
    ) -> None:
        bound_logger = logger.bind(tenant_id=tenant_id, webhook_id=webhook_id)
        bound_logger.info("delete_webhook.started", idempotency_key=idempotency_key)

        async with self.uow:
            if idempotency_key:
                is_completed, _res_body, _res_status = await self.uow.idempotency_repo.get_result(
                    tenant_id, idempotency_key
                )
                if is_completed:
                    bound_logger.info("delete_webhook.idempotent_result_returned")
                    return

            webhook = await self.uow.webhook_repo.find_by_id(tenant_id, webhook_id)
            if not webhook:
                bound_logger.error("delete_webhook.not_found")
                raise ResourceNotFoundError(
                    f"Webhook {webhook_id} not found for tenant {tenant_id}"
                )

            # Emitting deleted event before we actually delete the record
            webhook.add_domain_event(
                WebhookDeletedEvent(tenant_id=tenant_id, webhook_id=webhook_id)
            )

            # Persist successful result before destructive soft-delete
            if idempotency_key:
                await self.uow.idempotency_repo.save_result(
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                    response_body={},
                    response_status_code=204,
                )

            # Pass the loaded aggregate to delete_webhook so it can flush events
            await self.uow.webhook_repo.delete_webhook(
                webhook=webhook, deleted_by=deleted_by, idempotency_key=idempotency_key
            )
            await self.uow.commit()

            bound_logger.info("delete_webhook.completed")
