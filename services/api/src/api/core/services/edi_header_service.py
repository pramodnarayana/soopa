import logging
from collections.abc import Sequence
from uuid import UUID

from api.domain.models import (
    CreateOutboundEdiHeaderCmd,
    UpdateOutboundEdiHeaderCmd,
)
from api.ports.repository import ControlPlaneRepositoryPort
from database.models.control_plane import OutboundEdiHeader

logger = logging.getLogger(__name__)


class EdiHeaderService:
    """
    Domain service responsible for the lifecycle of Outbound EDI Headers.
    """

    def __init__(self, global_repo: ControlPlaneRepositoryPort) -> None:
        self.global_repo = global_repo

    async def create_outbound_edi_header(
        self, tenant_id: int, cmd: CreateOutboundEdiHeaderCmd
    ) -> UUID:
        logger.info(
            f"Creating Outbound EDI Header for trading partner {cmd.trading_partner_id} in tenant {tenant_id}"
        )
        header_id = await self.global_repo.create_outbound_edi_header(tenant_id=tenant_id, cmd=cmd)
        return header_id

    async def update_outbound_edi_header(
        self, tenant_id: int, header_id: UUID, cmd: UpdateOutboundEdiHeaderCmd
    ) -> bool:
        res = await self.global_repo.update_outbound_edi_header(tenant_id, header_id, cmd)
        return res

    async def delete_outbound_edi_header(self, tenant_id: int, header_id: UUID) -> bool:
        res = await self.global_repo.delete_outbound_edi_header(tenant_id, header_id)
        return res

    async def get_outbound_edi_headers(self, tenant_id: int) -> Sequence[OutboundEdiHeader]:
        return await self.global_repo.get_outbound_edi_headers(tenant_id)
