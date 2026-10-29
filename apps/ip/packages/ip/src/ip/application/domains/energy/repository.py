"""Typed SQLAlchemy repository for Energy MDM canonical domain tables."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ip.application.domains.energy.canonical import (
    CanonicalMeterReadingDTO,
    CanonicalServicePointDTO,
    MeterReadingQualityFlag,
    ServicePointStatus,
)
from ip.application.domains.energy.models import (
    MdmMeterReadingRecord,
    MdmServicePointRecord,
)
from ip.application.domains.energy.ports import EnergyDomainRepositoryPort


class SqlAlchemyEnergyDomainRepository(EnergyDomainRepositoryPort):
    """Repository persisting and querying dedicated Energy MDM canonical tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_meter_reading_dto(orm: MdmMeterReadingRecord) -> CanonicalMeterReadingDTO:
        return CanonicalMeterReadingDTO(
            id=orm.id,
            tenant_id=orm.tenant_id,
            trace_id=orm.trace_id,
            correlation_id=orm.correlation_id,
            parent_trace_id=orm.parent_trace_id,
            original_trace_id=orm.original_trace_id,
            replay_count=orm.replay_count,
            source_connection_id=orm.source_connection_id,
            source_replica_id=orm.source_replica_id,
            transformation_id=orm.transformation_id,
            transformation_version=orm.transformation_version,
            meter_serial_number=orm.meter_serial_number,
            service_point_id=orm.service_point_id,
            reading_timestamp=orm.reading_timestamp,
            interval_minutes=orm.interval_minutes,
            kwh_delivered=orm.kwh_delivered,
            kwh_received=orm.kwh_received,
            voltage_avg=orm.voltage_avg,
            quality_flag=orm.quality_flag,
            recorded_at=orm.recorded_at,
        )

    @staticmethod
    def _to_service_point_dto(orm: MdmServicePointRecord) -> CanonicalServicePointDTO:
        return CanonicalServicePointDTO(
            id=orm.id,
            tenant_id=orm.tenant_id,
            trace_id=orm.trace_id,
            correlation_id=orm.correlation_id,
            parent_trace_id=orm.parent_trace_id,
            original_trace_id=orm.original_trace_id,
            replay_count=orm.replay_count,
            source_connection_id=orm.source_connection_id,
            source_replica_id=orm.source_replica_id,
            transformation_id=orm.transformation_id,
            transformation_version=orm.transformation_version,
            service_point_external_id=orm.service_point_external_id,
            meter_serial_number=orm.meter_serial_number,
            customer_external_id=orm.customer_external_id,
            service_address=orm.service_address,
            grid_region=orm.grid_region,
            status=orm.status,
            updated_at=orm.updated_at,
        )

    async def save_meter_reading(self, dto: CanonicalMeterReadingDTO) -> None:
        orm = MdmMeterReadingRecord(
            id=dto.id,
            tenant_id=dto.tenant_id,
            trace_id=dto.trace_id,
            correlation_id=dto.correlation_id,
            parent_trace_id=dto.parent_trace_id,
            original_trace_id=dto.original_trace_id,
            replay_count=dto.replay_count,
            source_connection_id=dto.source_connection_id,
            source_replica_id=dto.source_replica_id,
            transformation_id=dto.transformation_id,
            transformation_version=dto.transformation_version,
            meter_serial_number=dto.meter_serial_number,
            service_point_id=dto.service_point_id,
            reading_timestamp=dto.reading_timestamp,
            interval_minutes=dto.interval_minutes,
            kwh_delivered=dto.kwh_delivered,
            kwh_received=dto.kwh_received,
            voltage_avg=dto.voltage_avg,
            quality_flag=dto.quality_flag,
            recorded_at=dto.recorded_at,
        )
        await self._session.merge(orm)
        await self._session.flush()

    async def list_readings_by_meter(
        self,
        tenant_id: str,
        meter_serial_number: str,
        limit: int = 100,
    ) -> Sequence[CanonicalMeterReadingDTO]:
        stmt = (
            select(MdmMeterReadingRecord)
            .where(
                MdmMeterReadingRecord.tenant_id == tenant_id,
                MdmMeterReadingRecord.meter_serial_number == meter_serial_number,
            )
            .order_by(MdmMeterReadingRecord.reading_timestamp.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [self._to_meter_reading_dto(r) for r in result.scalars().all()]

    async def save_service_point(self, dto: CanonicalServicePointDTO) -> None:
        existing_stmt = select(MdmServicePointRecord.id, MdmServicePointRecord.updated_at).where(
            MdmServicePointRecord.tenant_id == dto.tenant_id,
            MdmServicePointRecord.service_point_external_id == dto.service_point_external_id,
        )
        row = (await self._session.execute(existing_stmt)).one_or_none()
        if row is not None:
            existing_id, existing_updated_at = row
            if existing_updated_at is not None and existing_updated_at > dto.updated_at:
                return
            resolved_id = existing_id
        else:
            resolved_id = dto.id

        orm = MdmServicePointRecord(
            id=resolved_id,
            tenant_id=dto.tenant_id,
            trace_id=dto.trace_id,
            correlation_id=dto.correlation_id,
            parent_trace_id=dto.parent_trace_id,
            original_trace_id=dto.original_trace_id,
            replay_count=dto.replay_count,
            source_connection_id=dto.source_connection_id,
            source_replica_id=dto.source_replica_id,
            transformation_id=dto.transformation_id,
            transformation_version=dto.transformation_version,
            service_point_external_id=dto.service_point_external_id,
            meter_serial_number=dto.meter_serial_number,
            customer_external_id=dto.customer_external_id,
            service_address=dto.service_address,
            grid_region=dto.grid_region,
            status=dto.status,
            updated_at=dto.updated_at,
        )
        await self._session.merge(orm)
        await self._session.flush()

    async def get_service_point_by_external_id(
        self,
        tenant_id: str,
        service_point_external_id: str,
    ) -> CanonicalServicePointDTO | None:
        stmt = select(MdmServicePointRecord).where(
            MdmServicePointRecord.tenant_id == tenant_id,
            MdmServicePointRecord.service_point_external_id == service_point_external_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_service_point_dto(orm)

    async def soft_delete_service_point(
        self,
        tenant_id: str,
        service_point_external_id: str,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> None:
        stmt = (
            update(MdmServicePointRecord)
            .where(
                MdmServicePointRecord.tenant_id == tenant_id,
                MdmServicePointRecord.service_point_external_id == service_point_external_id,
            )
            .values(
                status=ServicePointStatus.DELETED.value,
                trace_id=trace_id,
                correlation_id=correlation_id,
                updated_at=datetime.now(UTC),
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def soft_delete_meter_reading_by_id(
        self,
        tenant_id: str,
        reading_id: str,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> None:
        stmt = (
            update(MdmMeterReadingRecord)
            .where(
                MdmMeterReadingRecord.tenant_id == tenant_id,
                MdmMeterReadingRecord.id == reading_id,
            )
            .values(
                quality_flag=MeterReadingQualityFlag.TOMBSTONED.value,
                trace_id=trace_id,
                correlation_id=correlation_id,
                recorded_at=datetime.now(UTC),
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def update_meter_reading_service_point(
        self,
        tenant_id: str,
        reading_id: str,
        service_point_id: str,
        trace_id: str,
    ) -> None:
        stmt = (
            update(MdmMeterReadingRecord)
            .where(
                MdmMeterReadingRecord.tenant_id == tenant_id,
                MdmMeterReadingRecord.id == reading_id,
            )
            .values(
                service_point_id=service_point_id,
                trace_id=trace_id,
                recorded_at=datetime.now(UTC),
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()
