from collections.abc import Sequence

import structlog

from edi.domain.routing.outbound_header import OutboundEdiHeader
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class GetOutboundEdiHeadersUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def get_outbound_edi_headers(self, tenant_id: str) -> Sequence[OutboundEdiHeader]:
        return await self.uow.edi_headers.get_outbound_edi_headers(tenant_id)
