import structlog
from edi.domain.events import EdiEventType, ProvisioningEvent

from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DeleteAS2PartnerUseCase:
    """
    Use Case for deleting an AS2 Trading Partner.
    """

    def __init__(self, uow: ControlPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self, tenant_id: str, partner_id: str, idempotency_key: str | None = None
    ) -> None:
        logger.info(
            "delete_as2_partner_started",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
        await self.uow.as2_partners.delete_as2_identity(tenant_id, partner_id)
        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_deleted,
                resource_id=str(partner_id),
            ),
            idempotency_key=idempotency_key,
        )

        logger.info(
            "delete_as2_partner_completed",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
