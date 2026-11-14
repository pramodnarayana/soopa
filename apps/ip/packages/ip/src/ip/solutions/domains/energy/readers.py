"""CanonicalReaderPort adapters for Energy Smart Grid MDM tables (`mdm_meter_readings`, `mdm_service_points`, `mdm_billing_readings`)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ip.engine.domain.normalization.normalized_record import NormalizedRecord
from ip.engine.domain.normalization.registries import CanonicalReaderRegistry
from ip.engine.ports.outbound.canonical_reader_port import (
    CanonicalReaderPort,
    CanonicalReaderRegistryPort,
)
from ip.solutions.domains.energy.canonical import EnergyEntityType
from ip.solutions.domains.energy.models import (
    MdmBillingReadingRecord,
    MdmMeterReadingRecord,
    MdmServicePointRecord,
)


def _meter_reading_to_normalized_record(orm: MdmMeterReadingRecord) -> NormalizedRecord:
    """Transforms an MdmMeterReadingRecord ORM row into an engine NormalizedRecord projection."""
    return NormalizedRecord(
        id=orm.id,
        tenant_id=orm.tenant_id,
        trace_id=orm.trace_id,
        correlation_id=orm.correlation_id,
        parent_trace_id=orm.parent_trace_id,
        original_trace_id=orm.original_trace_id,
        replay_count=orm.replay_count,
        connection_id=orm.source_connection_id,
        canonical_type=EnergyEntityType.MDM_METER_READING.value,
        source_id=orm.meter_serial_number,
        canonical_data={
            "meter_serial_number": orm.meter_serial_number,
            "service_point_id": orm.service_point_id,
            "reading_timestamp": orm.reading_timestamp.isoformat(),
            "interval_minutes": orm.interval_minutes,
            "kwh_delivered": orm.kwh_delivered,
            "kwh_received": orm.kwh_received,
            "voltage_avg": orm.voltage_avg,
            "quality_flag": orm.quality_flag,
            "canonical_id": orm.id,
            "transformation_id": orm.transformation_id,
            "transformation_version": orm.transformation_version,
        },
        normalized_at=orm.recorded_at,
    )


def _service_point_to_normalized_record(orm: MdmServicePointRecord) -> NormalizedRecord:
    """Transforms an MdmServicePointRecord ORM row into an engine NormalizedRecord projection."""
    return NormalizedRecord(
        id=orm.id,
        tenant_id=orm.tenant_id,
        trace_id=orm.trace_id,
        correlation_id=orm.correlation_id,
        parent_trace_id=orm.parent_trace_id,
        original_trace_id=orm.original_trace_id,
        replay_count=orm.replay_count,
        connection_id=orm.source_connection_id,
        canonical_type=EnergyEntityType.MDM_SERVICE_POINT.value,
        source_id=orm.service_point_external_id,
        canonical_data={
            "service_point_external_id": orm.service_point_external_id,
            "meter_serial_number": orm.meter_serial_number,
            "customer_external_id": orm.customer_external_id,
            "service_address": orm.service_address,
            "grid_region": orm.grid_region,
            "status": orm.status,
            "canonical_id": orm.id,
            "transformation_id": orm.transformation_id,
            "transformation_version": orm.transformation_version,
        },
        normalized_at=orm.updated_at,
    )


class SqlAlchemyMeterReadingCanonicalReader(CanonicalReaderPort):
    """Reads normalized `MDM_METER_READING` entities directly from `public.mdm_meter_readings`."""

    @property
    def canonical_type(self) -> str:
        return EnergyEntityType.MDM_METER_READING.value

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        record_id: str,
    ) -> NormalizedRecord | None:
        stmt = select(MdmMeterReadingRecord).where(
            MdmMeterReadingRecord.tenant_id == tenant_id,
            MdmMeterReadingRecord.id == record_id,
        )
        res = await session.execute(stmt)
        orm = res.scalar_one_or_none()
        return _meter_reading_to_normalized_record(orm) if orm is not None else None

    async def get_by_trace_id(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        trace_id: str,
    ) -> Sequence[NormalizedRecord]:
        stmt = (
            select(MdmMeterReadingRecord)
            .where(
                MdmMeterReadingRecord.tenant_id == tenant_id,
                MdmMeterReadingRecord.trace_id == trace_id,
            )
            .order_by(MdmMeterReadingRecord.reading_timestamp.asc())
        )
        res = await session.execute(stmt)
        return [_meter_reading_to_normalized_record(r) for r in res.scalars().all()]

    async def list_records(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        connection_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[NormalizedRecord]:
        stmt = select(MdmMeterReadingRecord).where(MdmMeterReadingRecord.tenant_id == tenant_id)
        if connection_id is not None:
            stmt = stmt.where(MdmMeterReadingRecord.source_connection_id == connection_id)
        stmt = (
            stmt.order_by(
                MdmMeterReadingRecord.reading_timestamp.desc(),
                MdmMeterReadingRecord.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        res = await session.execute(stmt)
        return [_meter_reading_to_normalized_record(r) for r in res.scalars().all()]


class SqlAlchemyServicePointCanonicalReader(CanonicalReaderPort):
    """Reads normalized `MDM_SERVICE_POINT` entities directly from `public.mdm_service_points`."""

    @property
    def canonical_type(self) -> str:
        return EnergyEntityType.MDM_SERVICE_POINT.value

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        record_id: str,
    ) -> NormalizedRecord | None:
        stmt = select(MdmServicePointRecord).where(
            MdmServicePointRecord.tenant_id == tenant_id,
            MdmServicePointRecord.id == record_id,
        )
        res = await session.execute(stmt)
        orm = res.scalar_one_or_none()
        return _service_point_to_normalized_record(orm) if orm is not None else None

    async def get_by_trace_id(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        trace_id: str,
    ) -> Sequence[NormalizedRecord]:
        stmt = (
            select(MdmServicePointRecord)
            .where(
                MdmServicePointRecord.tenant_id == tenant_id,
                MdmServicePointRecord.trace_id == trace_id,
            )
            .order_by(MdmServicePointRecord.updated_at.asc())
        )
        res = await session.execute(stmt)
        return [_service_point_to_normalized_record(sp) for sp in res.scalars().all()]

    async def list_records(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        connection_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[NormalizedRecord]:
        stmt = select(MdmServicePointRecord).where(MdmServicePointRecord.tenant_id == tenant_id)
        if connection_id is not None:
            stmt = stmt.where(MdmServicePointRecord.source_connection_id == connection_id)
        stmt = (
            stmt.order_by(
                MdmServicePointRecord.updated_at.desc(),
                MdmServicePointRecord.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        res = await session.execute(stmt)
        return [_service_point_to_normalized_record(sp) for sp in res.scalars().all()]


def _billing_reading_to_normalized_record(orm: MdmBillingReadingRecord) -> NormalizedRecord:
    """Transforms an MdmBillingReadingRecord ORM row into an engine NormalizedRecord projection."""
    return NormalizedRecord(
        id=orm.id,
        tenant_id=orm.tenant_id,
        trace_id=orm.trace_id,
        correlation_id=orm.correlation_id,
        parent_trace_id=orm.parent_trace_id,
        original_trace_id=orm.original_trace_id,
        replay_count=orm.replay_count,
        connection_id=orm.source_connection_id,
        canonical_type=EnergyEntityType.MDM_BILLING_READING.value,
        source_id=orm.reading_id,
        canonical_data={
            "reading_id": orm.reading_id,
            "meter_serial_number": orm.meter_serial_number,
            "service_point_id": orm.service_point_id,
            "reading_timestamp": orm.reading_timestamp.isoformat(),
            "kwh_delivered": orm.kwh_delivered,
            "quality_flag": orm.quality_flag,
            "canonical_id": orm.id,
            "transformation_id": orm.transformation_id,
            "transformation_version": orm.transformation_version,
        },
        normalized_at=orm.recorded_at,
    )


class SqlAlchemyBillingReadingCanonicalReader(CanonicalReaderPort):
    """Reads normalized `MDM_BILLING_READING` entities directly from `public.mdm_billing_readings`."""

    @property
    def canonical_type(self) -> str:
        return EnergyEntityType.MDM_BILLING_READING.value

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        record_id: str,
    ) -> NormalizedRecord | None:
        stmt = select(MdmBillingReadingRecord).where(
            MdmBillingReadingRecord.tenant_id == tenant_id,
            MdmBillingReadingRecord.id == record_id,
        )
        res = await session.execute(stmt)
        orm = res.scalar_one_or_none()
        return _billing_reading_to_normalized_record(orm) if orm is not None else None

    async def get_by_trace_id(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        trace_id: str,
    ) -> Sequence[NormalizedRecord]:
        stmt = (
            select(MdmBillingReadingRecord)
            .where(
                MdmBillingReadingRecord.tenant_id == tenant_id,
                MdmBillingReadingRecord.trace_id == trace_id,
            )
            .order_by(MdmBillingReadingRecord.reading_timestamp.asc())
        )
        res = await session.execute(stmt)
        return [_billing_reading_to_normalized_record(r) for r in res.scalars().all()]

    async def list_records(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        connection_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[NormalizedRecord]:
        stmt = select(MdmBillingReadingRecord).where(MdmBillingReadingRecord.tenant_id == tenant_id)
        if connection_id is not None:
            stmt = stmt.where(MdmBillingReadingRecord.source_connection_id == connection_id)
        stmt = (
            stmt.order_by(
                MdmBillingReadingRecord.reading_timestamp.desc(),
                MdmBillingReadingRecord.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        res = await session.execute(stmt)
        return [_billing_reading_to_normalized_record(r) for r in res.scalars().all()]


def register_energy_canonical_readers(
    registry: CanonicalReaderRegistryPort,
) -> None:
    """Register Energy Smart Grid MDM canonical readers (`MDM_METER_READING`, `MDM_SERVICE_POINT`, `MDM_BILLING_READING`)."""
    registry.register(SqlAlchemyMeterReadingCanonicalReader())
    registry.register(SqlAlchemyServicePointCanonicalReader())
    registry.register(SqlAlchemyBillingReadingCanonicalReader())


def create_default_canonical_reader_registry() -> CanonicalReaderRegistry[CanonicalReaderPort]:
    """Create and populate a CanonicalReaderRegistry with the Energy MDM canonical readers."""
    registry: CanonicalReaderRegistry[CanonicalReaderPort] = CanonicalReaderRegistry()
    register_energy_canonical_readers(registry)
    return registry


__all__ = [
    "SqlAlchemyBillingReadingCanonicalReader",
    "SqlAlchemyMeterReadingCanonicalReader",
    "SqlAlchemyServicePointCanonicalReader",
    "create_default_canonical_reader_registry",
    "register_energy_canonical_readers",
]
