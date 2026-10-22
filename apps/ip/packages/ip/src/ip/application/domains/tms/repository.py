"""Typed SQLAlchemy repository for TMS canonical domain tables."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ip.application.domains.tms.canonical import CanonicalCarrierDTO, CanonicalLoadDTO
from ip.application.domains.tms.models import TmsCarrierRecord, TmsLoadRecord


class SqlAlchemyTmsDomainRepository:
    """Repository persisting and querying dedicated TMS canonical tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_load_dto(orm: TmsLoadRecord) -> CanonicalLoadDTO:
        return CanonicalLoadDTO(
            id=orm.id,
            tenant_id=orm.tenant_id,
            trace_id=orm.trace_id,
            correlation_id=orm.correlation_id,
            parent_trace_id=orm.parent_trace_id,
            original_trace_id=orm.original_trace_id,
            replay_count=orm.replay_count,
            source_connection_id=orm.source_connection_id,
            source_replica_id=orm.source_replica_id,
            load_reference_number=orm.load_reference_number,
            carrier_scac=orm.carrier_scac,
            origin_city=orm.origin_city,
            origin_state=orm.origin_state,
            destination_city=orm.destination_city,
            destination_state=orm.destination_state,
            status=orm.status,
            total_weight_lbs=orm.total_weight_lbs,
            freight_charge_usd=orm.freight_charge_usd,
            pickup_scheduled_at=orm.pickup_scheduled_at,
            delivery_scheduled_at=orm.delivery_scheduled_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def _to_carrier_dto(orm: TmsCarrierRecord) -> CanonicalCarrierDTO:
        return CanonicalCarrierDTO(
            id=orm.id,
            tenant_id=orm.tenant_id,
            trace_id=orm.trace_id,
            correlation_id=orm.correlation_id,
            parent_trace_id=orm.parent_trace_id,
            original_trace_id=orm.original_trace_id,
            replay_count=orm.replay_count,
            source_connection_id=orm.source_connection_id,
            source_replica_id=orm.source_replica_id,
            scac_code=orm.scac_code,
            carrier_name=orm.carrier_name,
            dot_number=orm.dot_number,
            mc_number=orm.mc_number,
            safety_rating=orm.safety_rating,
            status=orm.status,
            updated_at=orm.updated_at,
        )

    async def save_load(self, dto: CanonicalLoadDTO) -> None:
        orm = TmsLoadRecord(
            id=dto.id,
            tenant_id=dto.tenant_id,
            trace_id=dto.trace_id,
            correlation_id=dto.correlation_id,
            parent_trace_id=dto.parent_trace_id,
            original_trace_id=dto.original_trace_id,
            replay_count=dto.replay_count,
            source_connection_id=dto.source_connection_id,
            source_replica_id=dto.source_replica_id,
            load_reference_number=dto.load_reference_number,
            carrier_scac=dto.carrier_scac,
            origin_city=dto.origin_city,
            origin_state=dto.origin_state,
            destination_city=dto.destination_city,
            destination_state=dto.destination_state,
            status=dto.status,
            total_weight_lbs=dto.total_weight_lbs,
            freight_charge_usd=dto.freight_charge_usd,
            pickup_scheduled_at=dto.pickup_scheduled_at,
            delivery_scheduled_at=dto.delivery_scheduled_at,
            updated_at=dto.updated_at,
        )
        await self._session.merge(orm)
        await self._session.flush()

    async def list_loads_by_status(
        self,
        tenant_id: str,
        status: str,
        limit: int = 100,
    ) -> Sequence[CanonicalLoadDTO]:
        stmt = (
            select(TmsLoadRecord)
            .where(
                TmsLoadRecord.tenant_id == tenant_id,
                TmsLoadRecord.status == status,
            )
            .order_by(TmsLoadRecord.updated_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [self._to_load_dto(r) for r in result.scalars().all()]

    async def save_carrier(self, dto: CanonicalCarrierDTO) -> None:
        orm = TmsCarrierRecord(
            id=dto.id,
            tenant_id=dto.tenant_id,
            trace_id=dto.trace_id,
            correlation_id=dto.correlation_id,
            parent_trace_id=dto.parent_trace_id,
            original_trace_id=dto.original_trace_id,
            replay_count=dto.replay_count,
            source_connection_id=dto.source_connection_id,
            source_replica_id=dto.source_replica_id,
            scac_code=dto.scac_code,
            carrier_name=dto.carrier_name,
            dot_number=dto.dot_number,
            mc_number=dto.mc_number,
            safety_rating=dto.safety_rating,
            status=dto.status,
            updated_at=dto.updated_at,
        )
        await self._session.merge(orm)
        await self._session.flush()
