from collections.abc import Sequence
from typing import Protocol

from domain.models import OutboundEdiHeaderDomainModel

from edi.domain.models import (
    CreateOutboundEdiHeaderCmd,
    UpdateOutboundEdiHeaderCmd,
)


class EdiHeaderRepositoryPort(Protocol):
    async def create_outbound_edi_header(
        self, tenant_id: str, cmd: CreateOutboundEdiHeaderCmd
    ) -> str: ...
    async def update_outbound_edi_header(
        self, tenant_id: str, header_id: str, cmd: UpdateOutboundEdiHeaderCmd
    ) -> bool: ...
    async def delete_outbound_edi_header(self, tenant_id: str, header_id: str) -> bool: ...
    async def get_outbound_edi_headers(
        self, tenant_id: str
    ) -> Sequence[OutboundEdiHeaderDomainModel]: ...
    async def get_outbound_edi_header_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> OutboundEdiHeaderDomainModel | None: ...
