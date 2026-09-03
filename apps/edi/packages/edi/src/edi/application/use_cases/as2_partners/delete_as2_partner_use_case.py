import structlog

from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
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
        aggregate = await self.uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not aggregate:
            return

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_deleted,
                resource_id=partner_id,
                explicit_idempotency_key=idempotency_key,
            )
        )

        await self.uow.as2_partners.delete(aggregate)

        logger.info(
            "delete_as2_partner_completed",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
