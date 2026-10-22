"""Pure Canonical Domain DTOs for Energy Smart Grid MDM (Meter Readings & Service Points)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CanonicalMeterReadingDTO:
    """Canonical representation of an AMI Smart Grid interval meter reading."""

    id: str
    tenant_id: str
    trace_id: str
    source_connection_id: str
    source_replica_id: str
    meter_serial_number: str
    service_point_id: str | None
    reading_timestamp: datetime
    interval_minutes: int
    kwh_delivered: float
    kwh_received: float
    voltage_avg: float | None
    quality_flag: str
    recorded_at: datetime
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0


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
    updated_at: datetime
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
