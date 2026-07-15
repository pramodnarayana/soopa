"""
Domain service responsible for the lifecycle of Webhook delivery destinations.

Follows Hexagonal Architecture:
  - Depends on ControlPlaneRepositoryPort (port), never on SQLAlchemy.
  - Pure Python: testable without a DB or framework.
"""

import logging
from uuid import UUID

from api.domain.models import CreateWebhookCmd, PartnerEntity
from api.ports.repository import ControlPlaneRepositoryPort
from domain.events import ProvisioningEventType

logger = logging.getLogger(__name__)


class WebhookService:
    """
    Application service responsible for the lifecycle of Webhook delivery destinations.

    Constructor receives ControlPlaneRepositoryPort — a pure interface.
    No framework, no DB, no network dependency at construction time.
    """

    def __init__(self, global_repo: ControlPlaneRepositoryPort) -> None:
        self._repo = global_repo

    async def create_webhook(self, tenant_id: int, cmd: CreateWebhookCmd) -> PartnerEntity:
        logger.info("Webhook creating", extra={"tenant_id": tenant_id, "webhook_name": cmd.name})
        partner_id = await self._repo.create_webhook(tenant_id=tenant_id, cmd=cmd)
        await self._repo.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.WEBHOOK_CREATED,
            payload={"partner_id": str(partner_id), "tenant_id": tenant_id},
        )
        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            type="WEBHOOK",
            status="ACTIVE",
        )

    async def update_webhook(
        self,
        tenant_id: int,
        webhook_id: UUID,
        name: str | None = None,
        active: bool | None = None,
        url: str | None = None,
    ) -> bool:
        logger.info(
            "Webhook updating", extra={"tenant_id": tenant_id, "webhook_id": str(webhook_id)}
        )
        result = await self._repo.update_webhook(tenant_id, webhook_id, name, active, url)
        if result:
            await self._repo.publish_outbox_event(
                tenant_id=tenant_id,
                event_type=ProvisioningEventType.WEBHOOK_UPDATED,
                payload={"partner_id": str(webhook_id), "tenant_id": tenant_id},
            )
        return result

    async def delete_webhook(self, tenant_id: int, webhook_id: UUID) -> bool:
        logger.info(
            "Webhook deleting", extra={"tenant_id": tenant_id, "webhook_id": str(webhook_id)}
        )
        result = await self._repo.delete_webhook(tenant_id, webhook_id)
        if result:
            await self._repo.publish_outbox_event(
                tenant_id=tenant_id,
                event_type=ProvisioningEventType.WEBHOOK_DELETED,
                payload={"partner_id": str(webhook_id), "tenant_id": tenant_id},
            )
        return result
