import structlog

from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class DeleteAS2PartnershipUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def delete_as2_partnership(self, tenant_id: str, partnership_id: str) -> None:
        logger.info(
            "Deleting AS2 partnership {partnership_id} for tenant {tenant_id}",
            partnership_id=partnership_id,
            tenant_id=tenant_id,
        )
        await self.uow.as2_partnerships.delete_as2_partnership(tenant_id, partnership_id)

        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partnership_deleted,
                resource_id=str(partnership_id),
            )
        )
