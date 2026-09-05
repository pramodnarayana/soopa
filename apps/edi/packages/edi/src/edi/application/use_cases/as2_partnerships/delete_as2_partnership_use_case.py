import structlog

from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class DeleteAS2PartnershipUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def delete_as2_partnership(self, tenant_id: str, partnership_id: str) -> None:
        logger.info(
            "edi_as2_partnership_deletion_started",
            partnership_id=partnership_id,
            tenant_id=tenant_id,
        )

        aggregate = await self.uow.as2_partnerships.get_as2_partnership(tenant_id, partnership_id)
        if not aggregate:
            return

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partnership_deleted,
                resource_id=str(partnership_id),
            )
        )

        await self.uow.as2_partnerships.delete(aggregate)

        logger.info(
            "edi_as2_partnership_deleted",
            partnership_id=partnership_id,
            tenant_id=tenant_id,
        )
