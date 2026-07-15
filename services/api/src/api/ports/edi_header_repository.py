from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from api.domain.models import (
    CreateOutboundEdiHeaderCmd,
    UpdateOutboundEdiHeaderCmd,
)
from domain.models import OutboundEdiHeaderDomainModel


class EdiHeaderRepositoryPort(Protocol):
    async def create_outbound_edi_header(
        self, tenant_id: int, cmd: CreateOutboundEdiHeaderCmd
    ) -> UUID: ...
    async def update_outbound_edi_header(
        self, tenant_id: int, header_id: UUID, cmd: UpdateOutboundEdiHeaderCmd
    ) -> bool: ...
    async def delete_outbound_edi_header(self, tenant_id: int, header_id: UUID) -> bool: ...
    async def get_outbound_edi_headers(
        self, tenant_id: int
    ) -> Sequence[OutboundEdiHeaderDomainModel]: ...
    async def get_outbound_edi_header_by_trading_partner_id(
        self, tenant_id: int, trading_partner_id: str
    ) -> OutboundEdiHeaderDomainModel | None: ...
