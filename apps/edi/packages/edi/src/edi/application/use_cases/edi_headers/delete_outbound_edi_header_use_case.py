import structlog

from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class DeleteOutboundEdiHeaderUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def delete_outbound_edi_header(self, tenant_id: str, header_id: str) -> bool:
        logger.info(
            "Deleting Outbound EDI Header {header_id} in tenant {tenant_id}",
            header_id=header_id,
            tenant_id=tenant_id,
        )
        success = await self.uow.edi_headers.delete_outbound_edi_header(tenant_id, header_id)

        if success:
            await self.uow.control_plane_outbox.publish_outbox_event(
                ProvisioningEvent(
                    tenant_id=tenant_id,
                    event_type=EdiEventType.edi_header_deleted,
                    resource_id=str(header_id),
                )
            )
            logger.info(
                "Published OUTBOUND_EDI_HEADER_DELETED outbox event for {header_id}",
                header_id=header_id,
            )

        return success
