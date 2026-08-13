from domain.events import ProvisioningEvent, WebhookEventType

from edi.ports.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork


class DeleteWebhookUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def execute(self, tenant_id: str, webhook_id: str) -> None:
        async with self.uow:
            await self.uow.webhooks.delete_webhook(tenant_id=tenant_id, webhook_id=webhook_id)
            await self.uow.control_plane_outbox.publish_outbox_event(
                ProvisioningEvent(
                    tenant_id=tenant_id,
                    event_type=WebhookEventType.webhook_deleted,
                    resource_id=webhook_id,
                )
            )
            await self.uow.commit()
