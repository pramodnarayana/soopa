from collections.abc import Sequence
from typing import Protocol

from edi.domain.models.headers import OutboundEdiHeaderDomainModel


class EdiHeaderRepositoryPort(Protocol):
    async def save(self, aggregate: OutboundEdiHeaderDomainModel) -> None: ...
    async def delete(self, aggregate: OutboundEdiHeaderDomainModel) -> None: ...
    async def get_outbound_edi_headers(
        self, tenant_id: str
    ) -> Sequence[OutboundEdiHeaderDomainModel]: ...
    async def get_outbound_edi_header(
        self, tenant_id: str, header_id: str
    ) -> OutboundEdiHeaderDomainModel | None: ...
    async def get_outbound_edi_header_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> OutboundEdiHeaderDomainModel | None: ...
