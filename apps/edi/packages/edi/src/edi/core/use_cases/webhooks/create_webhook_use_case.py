from domain.events import ProvisioningEvent, WebhookEventType
from domain.models import WebhookDomainModel

from edi.ports.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork


class CreateWebhookUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def execute(
        self,
        tenant_id: str,
        name: str,
        url: str,
        auth_header_vault_ref: str | None,
        idempotency_key: str | None = None,
    ) -> WebhookDomainModel:
        async with self.uow:
            webhook = await self.uow.webhooks.create_webhook(
                tenant_id=tenant_id,
                name=name,
                url=url,
                auth_header_vault_ref=auth_header_vault_ref,
            )
            await self.uow.control_plane_outbox.publish_outbox_event(
                ProvisioningEvent(
                    tenant_id=tenant_id,
                    event_type=WebhookEventType.webhook_created,
                    resource_id=webhook.id,
                ),
                idempotency_key=idempotency_key,
            )
            await self.uow.commit()
            return webhook
