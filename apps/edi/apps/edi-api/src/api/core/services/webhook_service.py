"""
Domain service responsible for the lifecycle of Webhook delivery destinations.

Follows Hexagonal Architecture:
  - Depends on UnitOfWork (port), never on SQLAlchemy.
  - Pure Python: testable without a DB or framework.
"""

import logging
from uuid import UUID

from domain.events import ProvisioningEventType
from domain.models import ConnectionType, PartnerStatus

from api.core.uow import UnitOfWork
from api.domain.models import CreateWebhookCmd, PartnerEntity

logger = logging.getLogger(__name__)


class WebhookService:
    """
    Application service responsible for the lifecycle of Webhook delivery destinations.

    Constructor receives UnitOfWork — a pure interface.
    No framework, no DB, no network dependency at construction time.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def create_webhook(self, tenant_id: str, cmd: CreateWebhookCmd) -> PartnerEntity:
        logger.info("Webhook creating", extra={"tenant_id": tenant_id, "webhook_name": cmd.name})
        partner_id = await self.uow.webhooks.create_webhook(tenant_id=tenant_id, cmd=cmd)
        await self.uow.control_plane_outbox.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.WEBHOOK_CREATED,
            payload={"partner_id": str(partner_id), "tenant_id": tenant_id},
        )
        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            type=ConnectionType.WEBHOOK,
            status=PartnerStatus.ACTIVE,
        )

    async def update_webhook(
        self,
        tenant_id: str,
        webhook_id: UUID,
        name: str | None = None,
        active: bool | None = None,
        url: str | None = None,
    ) -> bool:
        logger.info(
            "Webhook updating", extra={"tenant_id": tenant_id, "webhook_id": str(webhook_id)}
        )
        result = await self.uow.webhooks.update_webhook(tenant_id, webhook_id, name, active, url)
        if result:
            await self.uow.control_plane_outbox.publish_outbox_event(
                tenant_id=tenant_id,
                event_type=ProvisioningEventType.WEBHOOK_UPDATED,
                payload={"partner_id": str(webhook_id), "tenant_id": tenant_id},
            )
        return result

    async def delete_webhook(self, tenant_id: str, webhook_id: UUID) -> bool:
        logger.info(
            "Webhook deleting", extra={"tenant_id": tenant_id, "webhook_id": str(webhook_id)}
        )
        result = await self.uow.webhooks.delete_webhook(tenant_id, webhook_id)
        if result:
            await self.uow.control_plane_outbox.publish_outbox_event(
                tenant_id=tenant_id,
                event_type=ProvisioningEventType.WEBHOOK_DELETED,
                payload={"partner_id": str(webhook_id), "tenant_id": tenant_id},
            )
        return result
