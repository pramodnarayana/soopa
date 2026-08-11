import logging

from domain.events import ProvisioningEvent, WebhookEventType
from domain.models import WebhookDomainModel

from edi.ports.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = logging.getLogger(__name__)


class WebhookService:
    """
    Domain service responsible for the lifecycle of Webhooks.
    Operates on the Global Control Plane repository.
    """

    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_webhook(
        self,
        tenant_id: str,
        name: str,
        url: str,
        auth_header_vault_ref: str | None,
        idempotency_key: str | None = None,
    ) -> WebhookDomainModel:
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
        return webhook

    async def update_webhook(
        self,
        tenant_id: str,
        webhook_id: str,
        name: str | None,
        url: str | None,
        active: bool | None,
        idempotency_key: str | None = None,
    ) -> WebhookDomainModel:
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
        return webhook

    async def delete_webhook(self, tenant_id: str, webhook_id: str) -> None:
        await self.uow.webhooks.delete_webhook(tenant_id=tenant_id, webhook_id=webhook_id)
        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=WebhookEventType.webhook_deleted,
                resource_id=webhook_id,
            )
        )
