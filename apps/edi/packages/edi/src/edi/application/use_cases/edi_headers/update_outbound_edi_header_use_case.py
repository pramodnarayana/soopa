import structlog

from edi.application.dto import UpdateOutboundEdiHeaderCmd
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class UpdateOutboundEdiHeaderUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def update_outbound_edi_header(
        self, tenant_id: str, header_id: str, cmd: UpdateOutboundEdiHeaderCmd
    ) -> bool:
        logger.info(
            "Updating Outbound EDI Header {header_id} in tenant {tenant_id}",
            header_id=header_id,
            tenant_id=tenant_id,
        )
        success = await self.uow.edi_headers.update_outbound_edi_header(tenant_id, header_id, cmd)

        if success:
            await self.uow.control_plane_outbox.publish_outbox_event(
                ProvisioningEvent(
                    tenant_id=tenant_id,
                    event_type=EdiEventType.edi_header_updated,
                    resource_id=str(header_id),
                )
            )
            logger.info(
                "Published OUTBOUND_EDI_HEADER_UPDATED outbox event for {header_id}",
                header_id=header_id,
            )

        return success
