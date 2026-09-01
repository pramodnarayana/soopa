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
        aggregate = await self.uow.edi_headers.get_outbound_edi_header(tenant_id, header_id)
        if not aggregate:
            return False

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_header_deleted,
                resource_id=header_id,
            )
        )

        await self.uow.edi_headers.delete(aggregate)
        logger.info(
            "outbound_edi_header_deleted_domain_event_attached",
            header_id=header_id,
        )

        return True
