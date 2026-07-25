import logging
from collections.abc import Sequence
from uuid import UUID

from domain.models import OutboundEdiHeaderDomainModel

from api.core.uow import UnitOfWork
from api.domain.models import (
    CreateOutboundEdiHeaderCmd,
    UpdateOutboundEdiHeaderCmd,
)

logger = logging.getLogger(__name__)


class EdiHeaderService:
    """
    Domain service responsible for the lifecycle of Outbound EDI Headers.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def create_outbound_edi_header(
        self, tenant_id: int, cmd: CreateOutboundEdiHeaderCmd
    ) -> UUID:
        logger.info(
            f"Creating Outbound EDI Header for trading partner {cmd.trading_partner_id} in tenant {tenant_id}"
        )
        return await self.uow.edi_headers.create_outbound_edi_header(tenant_id=tenant_id, cmd=cmd)

    async def update_outbound_edi_header(
        self, tenant_id: int, header_id: UUID, cmd: UpdateOutboundEdiHeaderCmd
    ) -> bool:
        return await self.uow.edi_headers.update_outbound_edi_header(tenant_id, header_id, cmd)

    async def delete_outbound_edi_header(self, tenant_id: int, header_id: UUID) -> bool:
        return await self.uow.edi_headers.delete_outbound_edi_header(tenant_id, header_id)

    async def get_outbound_edi_headers(
        self, tenant_id: int
    ) -> Sequence[OutboundEdiHeaderDomainModel]:
        return await self.uow.edi_headers.get_outbound_edi_headers(tenant_id)
