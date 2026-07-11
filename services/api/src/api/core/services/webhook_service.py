import logging

from api.domain.models import CreateWebhookCmd, PartnerEntity
from api.ports.repository import ControlPlaneRepositoryPort
from domain.events import ProvisioningEventType

logger = logging.getLogger(__name__)


class WebhookService:
    """
    Domain service responsible for the lifecycle of Webhook delivery destinations.
    """

    def __init__(self, global_repo: ControlPlaneRepositoryPort) -> None:
        self.global_repo = global_repo

    async def create_webhook(self, tenant_id: int, cmd: CreateWebhookCmd) -> PartnerEntity:
        logger.info(f"Creating Webhook {cmd.name} for tenant {tenant_id}")
        partner_id = await self.global_repo.create_webhook(tenant_id=tenant_id, cmd=cmd)
        await self.global_repo.create_outbox_event(
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
