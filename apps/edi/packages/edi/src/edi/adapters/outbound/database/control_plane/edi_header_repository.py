from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update

from edi.adapters.outbound.database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import (
    OutboundEdiHeader as OrmOutboundEdiHeader,
)
from edi.domain.routing.outbound_header import OutboundEdiHeader
from edi.ports.outbound.edi_header_repository import EdiHeaderRepositoryPort


class SqlAlchemyEdiHeaderRepository(EdiHeaderRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    @staticmethod
    def _update_record_from_domain(
        record: OrmOutboundEdiHeader, aggregate: OutboundEdiHeader
    ) -> None:
        record.tenant_id = aggregate.tenant_id
        record.trading_partner_id = aggregate.trading_partner_id
        record.isa_sender_id = aggregate.isa_sender_id
        record.isa_receiver_id = aggregate.isa_receiver_id
        record.name = aggregate.name
        record.isa_sender_qualifier = aggregate.isa_sender_qualifier
        record.isa_receiver_qualifier = aggregate.isa_receiver_qualifier
        record.gs_sender_id = aggregate.gs_sender_id
        record.gs_receiver_id = aggregate.gs_receiver_id
        record.transaction_type = aggregate.transaction_type
        record.default_standard = aggregate.default_standard
        record.default_version = aggregate.default_version

    async def save(self, aggregate: OutboundEdiHeader) -> None:
        result = await self.session.execute(
            select(OrmOutboundEdiHeader).where(
                OrmOutboundEdiHeader.id == aggregate.id,
                OrmOutboundEdiHeader.tenant_id == aggregate.tenant_id,
                OrmOutboundEdiHeader.deleted_at.is_(None),
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            record = OrmOutboundEdiHeader(id=aggregate.id)
            self.session.add(record)

        self._update_record_from_domain(record, aggregate)

        await self._drain_events(aggregate)
        await self.session.flush()

    async def delete(self, aggregate: OutboundEdiHeader) -> None:
        await self.session.execute(
            update(OrmOutboundEdiHeader)
            .where(
                OrmOutboundEdiHeader.id == aggregate.id,
                OrmOutboundEdiHeader.tenant_id == aggregate.tenant_id,
                OrmOutboundEdiHeader.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC).replace(tzinfo=None))
        )
        await self._drain_events(aggregate)
        await self.session.flush()

    @staticmethod
    def _to_domain_model(record: OrmOutboundEdiHeader) -> OutboundEdiHeader:
        return OutboundEdiHeader(
            id=str(record.id),
            tenant_id=str(record.tenant_id),
            trading_partner_id=str(record.trading_partner_id),
            isa_sender_id=str(record.isa_sender_id),
            isa_receiver_id=str(record.isa_receiver_id),
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

    async def get_outbound_edi_header(
        self, tenant_id: str, header_id: str
    ) -> OutboundEdiHeader | None:
        stmt = select(OrmOutboundEdiHeader).where(
            OrmOutboundEdiHeader.tenant_id == tenant_id,
            OrmOutboundEdiHeader.id == header_id,
            OrmOutboundEdiHeader.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        return self._to_domain_model(record) if record else None

    async def get_outbound_edi_headers(self, tenant_id: str) -> Sequence[OutboundEdiHeader]:
        stmt = select(OrmOutboundEdiHeader).where(
            OrmOutboundEdiHeader.tenant_id == tenant_id, OrmOutboundEdiHeader.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return [self._to_domain_model(r) for r in result.scalars().all()]

    async def get_outbound_edi_header_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> OutboundEdiHeader | None:
        stmt = select(OrmOutboundEdiHeader).where(
            OrmOutboundEdiHeader.tenant_id == tenant_id,
            OrmOutboundEdiHeader.trading_partner_id == trading_partner_id,
            OrmOutboundEdiHeader.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        return self._to_domain_model(record) if record else None
