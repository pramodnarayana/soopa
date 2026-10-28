"""CanonicalWriterPort adapters for Energy Smart Grid MDM tables (`mdm_meter_readings`, `mdm_service_points`)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import structlog
from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id

from ip.application.domains.energy.canonical import (
    CanonicalMeterReadingDTO,
    CanonicalServicePointDTO,
    EnergyEntityType,
    MeterReadingQualityFlag,
    ServicePointStatus,
)
from ip.application.domains.energy.ports import EnergyDomainRepositoryPort
from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.models.global_entity_map import GlobalEntityMap
from ip.engine.domain.models.normalized_record import NormalizedRecord
from ip.engine.domain.services.canonical_writer_registry import (
    InMemoryCanonicalWriterRegistry,
)
from ip.engine.ports.outbound.canonical_writer_port import (
    CanonicalWriterPort,
    CanonicalWriterRegistryPort,
)
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)

EnergyRepoFactory = Callable[[IpDataPlaneUnitOfWorkPort], EnergyDomainRepositoryPort | None]


def _parse_iso_datetime(val: object) -> datetime:
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=UTC)
    if isinstance(val, str) and val.strip():
        normalized = val.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _parse_float(val: object, default: float = 0.0) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            return default
    return default


def _parse_optional_float(val: object) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str) and val.strip():
        try:
            return float(val)
        except ValueError:
            return None
    return None


def _parse_int(val: object, default: int = 15) -> int:
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        try:
            return int(val)
        except ValueError:
            return default
    return default


def _parse_optional_str(val: object) -> str | None:
    if val is None:
        return None
    text = str(val).strip()
    return text if text else None


async def _resolve_or_create_canonical_id(
    uow: IpDataPlaneUnitOfWorkPort,
    *,
    tenant_id: str,
    entity_domain: str,
    connection_id: str,
    source_id: str,
    trace_id: str,
    correlation_id: str | None,
) -> str:
    existing = await uow.entity_maps.get_by_source(
        tenant_id=tenant_id,
        entity_domain=entity_domain,
        source_connection_id=connection_id,
        source_entity_id=source_id,
    )
    if existing is not None:
        updated_gem = GlobalEntityMap(
            id=existing.id,
            tenant_id=existing.tenant_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            parent_trace_id=existing.parent_trace_id,
            original_trace_id=existing.original_trace_id,
            replay_count=existing.replay_count,
            entity_domain=existing.entity_domain,
            canonical_id=existing.canonical_id,
            source_connection_id=existing.source_connection_id,
            source_entity_id=existing.source_entity_id,
            dest_connection_id=existing.dest_connection_id,
            dest_entity_id=existing.dest_entity_id,
            created_at=existing.created_at,
        )
        await uow.entity_maps.save(updated_gem)
        return existing.canonical_id

    gem = GlobalEntityMap.create(
        tenant_id=tenant_id,
        entity_domain=entity_domain,
        canonical_id=generate_id(IpIdPrefix.NORMALIZED.value),
        source_connection_id=connection_id,
        source_entity_id=source_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
    )
    await uow.entity_maps.save(gem)
    return gem.canonical_id


class SqlAlchemyMeterReadingCanonicalWriter(CanonicalWriterPort):
    """Persists normalized `MDM_METER_READING` entities via an injected `EnergyDomainRepositoryPort` factory."""

    def __init__(self, repo_factory: EnergyRepoFactory) -> None:
        self._repo_factory = repo_factory

    @property
    def canonical_type(self) -> str:
        return EnergyEntityType.MDM_METER_READING.value

    async def upsert(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        fields: JsonDict,
        extensions: JsonDict,
        trace_id: str,
        transformation_id: str,
        transformation_version: int,
        replica_id: str,
        replica_version: int,
        correlation_id: str | None = None,
    ) -> None:
        canonical_id = await _resolve_or_create_canonical_id(
            uow,
            tenant_id=tenant_id,
            entity_domain=self.canonical_type,
            connection_id=connection_id,
            source_id=source_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        normalized_record = NormalizedRecord.create(
            tenant_id=tenant_id,
            connection_id=connection_id,
            canonical_type=self.canonical_type,
            source_id=source_id,
            canonical_data={
                **fields,
                "canonical_id": canonical_id,
                "transformation_id": transformation_id,
                "transformation_version": transformation_version,
                "extensions": dict(extensions),
            },
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        await uow.normalized_records.save(normalized_record)

        repo = self._repo_factory(uow)
        if repo is not None:
            reading_dto = CanonicalMeterReadingDTO(
                id=canonical_id,
                tenant_id=tenant_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                source_connection_id=connection_id,
                source_replica_id=replica_id,
                transformation_id=transformation_id,
                transformation_version=transformation_version,
                meter_serial_number=str(fields.get("meter_serial_number") or source_id),
                service_point_id=_parse_optional_str(fields.get("service_point_id")),
                reading_timestamp=_parse_iso_datetime(fields.get("reading_timestamp")),
                interval_minutes=_parse_int(fields.get("interval_minutes"), 15),
                kwh_delivered=_parse_float(fields.get("kwh_delivered"), 0.0),
                kwh_received=_parse_float(fields.get("kwh_received"), 0.0),
                voltage_avg=_parse_optional_float(fields.get("voltage_avg")),
                quality_flag=str(
                    fields.get("quality_flag") or MeterReadingQualityFlag.VALIDATED.value
                ),
                recorded_at=datetime.now(UTC),
            )
            await repo.save_meter_reading(reading_dto)

        logger.info(
            "energy_meter_reading_canonical_upserted",
            tenant_id=tenant_id,
            connection_id=connection_id,
            canonical_id=canonical_id,
            source_id=source_id,
            transformation_id=transformation_id,
            transformation_version=transformation_version,
            trace_id=trace_id,
        )

    async def soft_delete(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> None:
        gem = await uow.entity_maps.get_by_source(
            tenant_id=tenant_id,
            entity_domain=self.canonical_type,
            source_connection_id=connection_id,
            source_entity_id=source_id,
        )
        repo = self._repo_factory(uow)
        if gem is not None and repo is not None:
            await repo.soft_delete_meter_reading_by_id(
                tenant_id=tenant_id,
                reading_id=gem.canonical_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
            )
            logger.info(
                "energy_meter_reading_canonical_soft_deleted",
                tenant_id=tenant_id,
                canonical_id=gem.canonical_id,
                source_id=source_id,
                trace_id=trace_id,
            )

    async def resolve_id(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
    ) -> str | None:
        gem = await uow.entity_maps.get_by_source(
            tenant_id=tenant_id,
            entity_domain=self.canonical_type,
            source_connection_id=connection_id,
            source_entity_id=source_id,
        )
        if gem is None:
            return None
        return gem.canonical_id

    async def resolve_reference(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        field_name: str,
        target_id: str,
        trace_id: str,
    ) -> None:
        if field_name != "service_point_id":
            return
        gem = await uow.entity_maps.get_by_source(
            tenant_id=tenant_id,
            entity_domain=self.canonical_type,
            source_connection_id=connection_id,
            source_entity_id=source_id,
        )
        repo = self._repo_factory(uow)
        if gem is not None and repo is not None:
            await repo.update_meter_reading_service_point(
                tenant_id=tenant_id,
                reading_id=gem.canonical_id,
                service_point_id=target_id,
                trace_id=trace_id,
            )
            logger.info(
                "energy_meter_reading_reference_resolved",
                tenant_id=tenant_id,
                canonical_id=gem.canonical_id,
                field_name=field_name,
                target_id=target_id,
                trace_id=trace_id,
            )


class SqlAlchemyServicePointCanonicalWriter(CanonicalWriterPort):
    """Persists normalized `MDM_SERVICE_POINT` entities via an injected `EnergyDomainRepositoryPort` factory."""

    def __init__(self, repo_factory: EnergyRepoFactory) -> None:
        self._repo_factory = repo_factory

    @property
    def canonical_type(self) -> str:
        return EnergyEntityType.MDM_SERVICE_POINT.value

    async def upsert(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        fields: JsonDict,
        extensions: JsonDict,
        trace_id: str,
        transformation_id: str,
        transformation_version: int,
        replica_id: str,
        replica_version: int,
        correlation_id: str | None = None,
    ) -> None:
        canonical_id = await _resolve_or_create_canonical_id(
            uow,
            tenant_id=tenant_id,
            entity_domain=self.canonical_type,
            connection_id=connection_id,
            source_id=source_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        normalized_record = NormalizedRecord.create(
            tenant_id=tenant_id,
            connection_id=connection_id,
            canonical_type=self.canonical_type,
            source_id=source_id,
            canonical_data={
                **fields,
                "canonical_id": canonical_id,
                "transformation_id": transformation_id,
                "transformation_version": transformation_version,
                "extensions": dict(extensions),
            },
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        await uow.normalized_records.save(normalized_record)

        repo = self._repo_factory(uow)
        if repo is not None:
            sp_dto = CanonicalServicePointDTO(
                id=canonical_id,
                tenant_id=tenant_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                source_connection_id=connection_id,
                source_replica_id=replica_id,
                transformation_id=transformation_id,
                transformation_version=transformation_version,
                service_point_external_id=str(fields.get("service_point_external_id") or source_id),
                meter_serial_number=_parse_optional_str(fields.get("meter_serial_number")),
                customer_external_id=_parse_optional_str(fields.get("customer_external_id")),
                service_address=_parse_optional_str(fields.get("service_address")),
                grid_region=_parse_optional_str(fields.get("grid_region")),
                status=str(fields.get("status") or ServicePointStatus.ACTIVE.value),
                updated_at=datetime.now(UTC),
            )
            await repo.save_service_point(sp_dto)

        logger.info(
            "energy_service_point_canonical_upserted",
            tenant_id=tenant_id,
            connection_id=connection_id,
            canonical_id=canonical_id,
            source_id=source_id,
            transformation_id=transformation_id,
            transformation_version=transformation_version,
            trace_id=trace_id,
        )

    async def soft_delete(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        trace_id: str,
        correlation_id: str | None = None,
    ) -> None:
        repo = self._repo_factory(uow)
        if repo is not None:
            await repo.soft_delete_service_point(
                tenant_id=tenant_id,
                service_point_external_id=source_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
            )
            logger.info(
                "energy_service_point_canonical_soft_deleted",
                tenant_id=tenant_id,
                source_id=source_id,
                trace_id=trace_id,
            )

    async def resolve_id(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
    ) -> str | None:
        repo = self._repo_factory(uow)
        if repo is not None:
            sp = await repo.get_service_point_by_external_id(
                tenant_id=tenant_id,
                service_point_external_id=source_id,
            )
            if sp is not None:
                if sp.status == ServicePointStatus.DELETED.value:
                    return None
                return sp.id

        gem = await uow.entity_maps.get_by_source(
            tenant_id=tenant_id,
            entity_domain=self.canonical_type,
            source_connection_id=connection_id,
            source_entity_id=source_id,
        )
        if gem is None:
            return None
        return gem.canonical_id

    async def resolve_reference(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        *,
        tenant_id: str,
        connection_id: str,
        source_id: str,
        field_name: str,
        target_id: str,
        trace_id: str,
    ) -> None:
        return None


def register_energy_canonical_writers(
    registry: CanonicalWriterRegistryPort,
    repo_factory: EnergyRepoFactory,
) -> None:
    """Register Energy Smart Grid MDM canonical writers (`MDM_METER_READING`, `MDM_SERVICE_POINT`)."""
    registry.register(SqlAlchemyMeterReadingCanonicalWriter(repo_factory=repo_factory))
    registry.register(SqlAlchemyServicePointCanonicalWriter(repo_factory=repo_factory))


def create_default_canonical_writer_registry(
    repo_factory: EnergyRepoFactory,
) -> InMemoryCanonicalWriterRegistry[CanonicalWriterPort]:
    """Create and populate a CanonicalWriterRegistry with the Energy MDM canonical writers."""
    registry: InMemoryCanonicalWriterRegistry[CanonicalWriterPort] = (
        InMemoryCanonicalWriterRegistry()
    )
    register_energy_canonical_writers(registry, repo_factory=repo_factory)
    return registry


__all__ = [
    "EnergyRepoFactory",
    "SqlAlchemyMeterReadingCanonicalWriter",
    "SqlAlchemyServicePointCanonicalWriter",
    "create_default_canonical_writer_registry",
    "register_energy_canonical_writers",
]
