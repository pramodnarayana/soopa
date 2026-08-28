import structlog

from edi.application.dto import UpdateAS2PartnershipCmd
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models import AS2PartnershipDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class UpdateAS2PartnershipUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def update_as2_partnership(
        self, tenant_id: str, partnership_id: str, cmd: UpdateAS2PartnershipCmd
    ) -> AS2PartnershipDomainModel:
        logger.info("Updating AS2 partnership {partnership_id}", partnership_id=partnership_id)
        await self.uow.as2_partnerships.update_as2_partnership(
            tenant_id=tenant_id, partnership_id=partnership_id, cmd=cmd
        )
        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partnership_updated,
                resource_id=str(partnership_id),
            )
        )
        updated = await self.uow.as2_partnerships.get_as2_partnership(tenant_id, partnership_id)
        if not updated:
            raise ValueError(f"AS2 partnership {partnership_id} not found")

        return updated
