from domain.events import ProvisioningEvent, WebhookEventType
from domain.models import WebhookDomainModel

from edi.ports.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork


class UpdateWebhookUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
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
        async with self.uow:
            webhook = await self.uow.webhooks.update_webhook(
                tenant_id=tenant_id,
                webhook_id=webhook_id,
                name=name,
                url=url,
                active=active,
            )
            await self.uow.control_plane_outbox.publish_outbox_event(
                ProvisioningEvent(
                    tenant_id=tenant_id,
                    event_type=WebhookEventType.webhook_updated,
                    resource_id=webhook.id,
                ),
                idempotency_key=idempotency_key,
            )
            await self.uow.commit()
            return webhook
