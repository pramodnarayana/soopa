"""Pure Canonical Domain DTOs for Energy Smart Grid MDM (Meter Readings, Service Points & Outages)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from seedwork.utils import generate_id


class EnergyEntityType(StrEnum):
    """Canonical domain entity types for the Energy vertical."""

    MDM_METER_READING = "MDM_METER_READING"
    MDM_SERVICE_POINT = "MDM_SERVICE_POINT"
    MDM_BILLING_READING = "MDM_BILLING_READING"
    MDM_OUTAGE_EVENT = "MDM_OUTAGE_EVENT"


class EnergyIdPrefix(StrEnum):
    """Canonical entity ID prefixes for the Energy Smart Grid MDM vertical."""

    MDM_READING = "ip_mdmr"
    MDM_SERVICE_POINT = "ip_mdms"
    MDM_BILLING_READING = "ip_mdmb"
    MDM_OUTAGE = "ip_outage"


class MeterReadingQualityFlag(StrEnum):
    """Canonical quality flags for AMI Smart Grid interval meter readings."""

    VALIDATED = "VALIDATED"
    ESTIMATED = "ESTIMATED"
    TOMBSTONED = "TOMBSTONED"


class ServicePointStatus(StrEnum):
    """Canonical lifecycle statuses for Energy utility service points."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DELETED = "DELETED"


@dataclass(frozen=True)
class CanonicalMeterReadingDTO:
    """Canonical representation of an AMI Smart Grid interval meter reading."""

    id: str = field(default_factory=lambda: generate_id(EnergyIdPrefix.MDM_READING.value))
    tenant_id: str = ""
    trace_id: str = field(default_factory=lambda: generate_id("trace"))
    source_connection_id: str = "conn_default"
    source_replica_id: str = "rep_default"
    meter_serial_number: str = ""
    service_point_id: str | None = None
    reading_timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    interval_minutes: int = 15
    kwh_delivered: float = 0.0
    kwh_received: float = 0.0
    voltage_avg: float | None = None
    quality_flag: str = MeterReadingQualityFlag.VALIDATED.value
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    transformation_id: str = "energy.ami_meter_reading"
    transformation_version: int = 1
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0

    def __init__(
        self,
        id: str | None = None,
        tenant_id: str = "",
        trace_id: str | None = None,
        source_connection_id: str = "conn_default",
        source_replica_id: str = "rep_default",
        meter_serial_number: str = "",
        service_point_id: str | None = None,
        reading_timestamp: datetime | None = None,
        interval_minutes: int = 15,
        kwh_delivered: float = 0.0,
        kwh_received: float = 0.0,
        voltage_avg: float | None = None,
        quality_flag: str = MeterReadingQualityFlag.VALIDATED.value,
        recorded_at: datetime | None = None,
        transformation_id: str = "energy.ami_meter_reading",
        transformation_version: int = 1,
        correlation_id: str | None = None,
        parent_trace_id: str | None = None,
        original_trace_id: str | None = None,
        replay_count: int = 0,
        *,
        interval_end_utc: datetime | None = None,
        quality_flags: tuple[MeterReadingQualityFlag | str, ...] | None = None,
    ) -> None:
        effective_ts = reading_timestamp or interval_end_utc or datetime.now(UTC)
        effective_id = id or generate_id(EnergyIdPrefix.MDM_READING.value)
        effective_trace = trace_id or generate_id("trace")
        effective_quality = quality_flag
        if quality_flags:
            val = quality_flags[0]
            effective_quality = val.value if isinstance(val, MeterReadingQualityFlag) else str(val)
        object.__setattr__(self, "id", effective_id)
        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(self, "trace_id", effective_trace)
        object.__setattr__(self, "source_connection_id", source_connection_id)
        object.__setattr__(self, "source_replica_id", source_replica_id)
        object.__setattr__(self, "meter_serial_number", meter_serial_number)
        object.__setattr__(self, "service_point_id", service_point_id)
        object.__setattr__(self, "reading_timestamp", effective_ts)
        object.__setattr__(self, "interval_minutes", interval_minutes)
        object.__setattr__(self, "kwh_delivered", kwh_delivered)
        object.__setattr__(self, "kwh_received", kwh_received)
        object.__setattr__(self, "voltage_avg", voltage_avg)
        object.__setattr__(self, "quality_flag", effective_quality)
        object.__setattr__(self, "recorded_at", recorded_at or datetime.now(UTC))
        object.__setattr__(self, "transformation_id", transformation_id)
        object.__setattr__(self, "transformation_version", transformation_version)
        object.__setattr__(self, "correlation_id", correlation_id)
        object.__setattr__(self, "parent_trace_id", parent_trace_id)
        object.__setattr__(self, "original_trace_id", original_trace_id)
        object.__setattr__(self, "replay_count", replay_count)

    @property
    def interval_end_utc(self) -> datetime:
        """Alias for reading_timestamp conforming to universal interval columnar format."""
        return self.reading_timestamp

    @property
    def quality_flags(self) -> tuple[MeterReadingQualityFlag, ...]:
        """Sequence view of quality flags for columnar batching."""
        try:
            return (MeterReadingQualityFlag(self.quality_flag),)
        except ValueError:
            return (MeterReadingQualityFlag.VALIDATED,)


@dataclass(frozen=True)
class CanonicalServicePointDTO:
    """Canonical representation of an Energy utility service point / premise."""

    id: str
    tenant_id: str
    trace_id: str
    source_connection_id: str
    source_replica_id: str
    service_point_external_id: str
    meter_serial_number: str | None
    customer_external_id: str | None
    service_address: str | None
    grid_region: str | None
    status: str
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    transformation_id: str = "energy.ami_service_point"
    transformation_version: int = 1
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0


@dataclass(frozen=True)
class CanonicalBillingReadingDTO:
    """Canonical representation of an Energy utility billing determinant / register reading."""

    id: str
    tenant_id: str
    trace_id: str
    source_connection_id: str
    source_replica_id: str
    reading_id: str
    meter_serial_number: str
    reading_timestamp: datetime
    kwh_delivered: float
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    service_point_id: str | None = None
    quality_flag: str = MeterReadingQualityFlag.VALIDATED.value
    transformation_id: str = "energy.sap_billing_reading"
    transformation_version: int = 1
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0


@dataclass(frozen=True)
class CanonicalOutageEventDTO:
    """Canonical representation of an AMI power outage or restoration event."""

    id: str
    tenant_id: str
    trace_id: str
    source_connection_id: str
    source_replica_id: str
    event_type: str
    meter_serial_number: str
    event_timestamp: datetime
    severity: str
    affected_customers: int
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    service_point_id: str | None = None
    transformation_id: str = "energy.outage_event"
    transformation_version: int = 1
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0


__all__ = [
    "CanonicalBillingReadingDTO",
    "CanonicalMeterReadingDTO",
    "CanonicalOutageEventDTO",
    "CanonicalServicePointDTO",
    "EnergyEntityType",
    "EnergyIdPrefix",
    "MeterReadingQualityFlag",
    "ServicePointStatus",
]
