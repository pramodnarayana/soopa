import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update

from edi.adapters.outbound.database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import OutboundEdiHeader
from edi.domain.models.headers import OutboundEdiHeaderDomainModel
from edi.ports.outbound.edi_header_repository import EdiHeaderRepositoryPort


class SqlAlchemyEdiHeaderRepository(EdiHeaderRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    async def save(self, aggregate: OutboundEdiHeaderDomainModel) -> None:
        result = await self.session.execute(
            select(OutboundEdiHeader).where(
                OutboundEdiHeader.id == aggregate.id,
                OutboundEdiHeader.tenant_id == aggregate.tenant_id,
                OutboundEdiHeader.deleted_at.is_(None),
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            record = OutboundEdiHeader(id=aggregate.id)
            self.session.add(record)

        for field in dataclasses.fields(aggregate):
            if field.name not in ("created_at", "updated_at", "_domain_events") and hasattr(
                record, field.name
            ):
                setattr(record, field.name, getattr(aggregate, field.name))

        self._drain_events(aggregate)
        await self.session.flush()

    async def delete(self, aggregate: OutboundEdiHeaderDomainModel) -> None:
        await self.session.execute(
            update(OutboundEdiHeader)
            .where(
                OutboundEdiHeader.id == aggregate.id,
                OutboundEdiHeader.tenant_id == aggregate.tenant_id,
                OutboundEdiHeader.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC).replace(tzinfo=None))
        )
        self._drain_events(aggregate)
        await self.session.flush()

    def _map_record_to_domain(self, record: OutboundEdiHeader) -> OutboundEdiHeaderDomainModel:
        kwargs = {
            f.name: getattr(record, f.name)
            for f in dataclasses.fields(OutboundEdiHeaderDomainModel)
            if hasattr(record, f.name)
            and f.name
            not in (
                "id",
                "tenant_id",
                "trading_partner_id",
                "isa_sender_id",
                "isa_receiver_id",
                "created_at",
                "updated_at",
            )
        }
        return OutboundEdiHeaderDomainModel(
            id=str(record.id),
            tenant_id=str(record.tenant_id),
            trading_partner_id=str(record.trading_partner_id),
            isa_sender_id=str(record.isa_sender_id),
            isa_receiver_id=str(record.isa_receiver_id),
            created_at=record.created_at,
            updated_at=record.updated_at,
            **kwargs,
        )

    async def get_outbound_edi_header(
        self, tenant_id: str, header_id: str
    ) -> OutboundEdiHeaderDomainModel | None:
        stmt = select(OutboundEdiHeader).where(
            OutboundEdiHeader.tenant_id == tenant_id,
            OutboundEdiHeader.id == header_id,
            OutboundEdiHeader.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        return self._map_record_to_domain(record) if record else None

    async def get_outbound_edi_headers(
        self, tenant_id: str
    ) -> Sequence[OutboundEdiHeaderDomainModel]:
        stmt = select(OutboundEdiHeader).where(
            OutboundEdiHeader.tenant_id == tenant_id, OutboundEdiHeader.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return [self._map_record_to_domain(r) for r in result.scalars().all()]

    async def get_outbound_edi_header_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> OutboundEdiHeaderDomainModel | None:
        stmt = select(OutboundEdiHeader).where(
            OutboundEdiHeader.tenant_id == tenant_id,
            OutboundEdiHeader.trading_partner_id == trading_partner_id,
            OutboundEdiHeader.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        return self._map_record_to_domain(record) if record else None
