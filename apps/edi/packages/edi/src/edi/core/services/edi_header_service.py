import logging
from collections.abc import Sequence

from domain.events import EdiEventType, ProvisioningEvent
from domain.models import OutboundEdiHeaderDomainModel

from edi.domain.models import (
    CreateOutboundEdiHeaderCmd,
    UpdateOutboundEdiHeaderCmd,
)
from edi.ports.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = logging.getLogger(__name__)


class EdiHeaderService:
    """
    Domain service responsible for the lifecycle of Outbound EDI Headers.
    """

    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_outbound_edi_header(
        self, tenant_id: str, cmd: CreateOutboundEdiHeaderCmd
    ) -> str:
        logger.info(
            f"Creating Outbound EDI Header for trading partner {cmd.trading_partner_id} in tenant {tenant_id}"
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
        logger.info(f"Published OUTBOUND_EDI_HEADER_CREATED outbox event for {header_id}")
        return header_id

    async def update_outbound_edi_header(
        self, tenant_id: str, header_id: str, cmd: UpdateOutboundEdiHeaderCmd
    ) -> bool:
        logger.info(f"Updating Outbound EDI Header {header_id} in tenant {tenant_id}")
        success = await self.uow.edi_headers.update_outbound_edi_header(tenant_id, header_id, cmd)

        if success:
            await self.uow.control_plane_outbox.publish_outbox_event(
                ProvisioningEvent(
                    tenant_id=tenant_id,
                    event_type=EdiEventType.edi_header_updated,
                    resource_id=str(header_id),
                )
            )
            logger.info(f"Published OUTBOUND_EDI_HEADER_UPDATED outbox event for {header_id}")

        return success

    async def delete_outbound_edi_header(self, tenant_id: str, header_id: str) -> bool:
        logger.info(f"Deleting Outbound EDI Header {header_id} in tenant {tenant_id}")
        success = await self.uow.edi_headers.delete_outbound_edi_header(tenant_id, header_id)

        if success:
            await self.uow.control_plane_outbox.publish_outbox_event(
                ProvisioningEvent(
                    tenant_id=tenant_id,
                    event_type=EdiEventType.edi_header_deleted,
                    resource_id=str(header_id),
                )
            )
            logger.info(f"Published OUTBOUND_EDI_HEADER_DELETED outbox event for {header_id}")

        return success

    async def get_outbound_edi_headers(
        self, tenant_id: str
    ) -> Sequence[OutboundEdiHeaderDomainModel]:
        return await self.uow.edi_headers.get_outbound_edi_headers(tenant_id)
