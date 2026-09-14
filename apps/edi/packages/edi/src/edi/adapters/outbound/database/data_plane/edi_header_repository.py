from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.data_plane.exceptions import ReadOnlyDataPlaneRepositoryError
from edi.adapters.outbound.database.models.data_plane import OutboundEdiHeader
from edi.domain.models.headers import OutboundEdiHeaderDomainModel
from edi.ports.outbound.edi_header_repository import EdiHeaderRepositoryPort


class SqlAlchemyDataPlaneEdiHeaderRepository(EdiHeaderRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: OutboundEdiHeaderDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: OutboundEdiHeaderDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_outbound_edi_header(
        self, tenant_id: str, header_id: str
    ) -> OutboundEdiHeaderDomainModel | None:
        stmt = select(OutboundEdiHeader).where(
            OutboundEdiHeader.tenant_id == tenant_id, OutboundEdiHeader.id == header_id
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_outbound_edi_header_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> OutboundEdiHeaderDomainModel | None:
        stmt = select(OutboundEdiHeader).where(
            OutboundEdiHeader.tenant_id == tenant_id,
            OutboundEdiHeader.trading_partner_id == trading_partner_id,
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_outbound_edi_headers(
        self, tenant_id: str
    ) -> Sequence[OutboundEdiHeaderDomainModel]:
        stmt = select(OutboundEdiHeader).where(OutboundEdiHeader.tenant_id == tenant_id)
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    @staticmethod
    def _to_domain_model(record: OutboundEdiHeader) -> OutboundEdiHeaderDomainModel:
        return OutboundEdiHeaderDomainModel(
            id=record.id,
            tenant_id=record.tenant_id,
            trading_partner_id=record.trading_partner_id,
            isa_sender_id=record.isa_sender_id,
            isa_receiver_id=record.isa_receiver_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            name=record.name,
            isa_sender_qualifier=record.isa_sender_qualifier,
            isa_receiver_qualifier=record.isa_receiver_qualifier,
            gs_sender_id=record.gs_sender_id,
            gs_receiver_id=record.gs_receiver_id,
            transaction_type=record.transaction_type,
            default_standard=record.default_standard,
            default_version=record.default_version,
        )
