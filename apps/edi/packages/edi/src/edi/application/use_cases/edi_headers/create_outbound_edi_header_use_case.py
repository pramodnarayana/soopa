import structlog

from edi.application.dto import CreateOutboundEdiHeaderCmd
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class CreateOutboundEdiHeaderUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_outbound_edi_header(
        self, tenant_id: str, cmd: CreateOutboundEdiHeaderCmd
    ) -> str:
        logger.info(
            "Creating Outbound EDI Header for trading partner {cmd_trading_partner_id} in tenant {tenant_id}",
            cmd_trading_partner_id=cmd.trading_partner_id,
            tenant_id=tenant_id,
        )
        header_id = await self.uow.edi_headers.create_outbound_edi_header(
            tenant_id=tenant_id, cmd=cmd
        )

        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_header_created,
                resource_id=str(header_id),
            )
        )
        logger.info(
            "Published OUTBOUND_EDI_HEADER_CREATED outbox event for {header_id}",
            header_id=header_id,
        )
        return header_id
