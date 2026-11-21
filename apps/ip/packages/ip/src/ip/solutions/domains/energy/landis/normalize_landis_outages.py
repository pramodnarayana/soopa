"""Pure functional canonical normalizer for Landis+Gyr outage events."""

from __future__ import annotations

from datetime import UTC, datetime

from seedwork.domain.types import JsonDict

from ip.sdk import (
    TransformerSpec,
    parse_iso_datetime,
    safe_int,
)
from ip.solutions.domains.energy.canonical import CanonicalOutageEventDTO


def normalize_landis_outage(raw: JsonDict) -> CanonicalOutageEventDTO:
    """Pure canonical normalizer mapping raw Landis outage JSON into CanonicalOutageEventDTO.

    Zero decorators. Zero database calls. Zero external mocks required for testing.
    """
    event_id = str(raw.get("event_id") or raw.get("id") or "").strip()
    if not event_id:
        raise ValueError("Raw Landis outage record missing required event_id")

    timestamp_raw = raw.get("timestamp") or raw.get("event_time") or raw.get("start_time")
    if not timestamp_raw:
        raise ValueError("Raw Landis outage record missing required timestamp")

    event_dt = parse_iso_datetime(timestamp_raw)

    return CanonicalOutageEventDTO(
        id=f"outage_landis_{event_id}_{int(event_dt.timestamp())}",
        tenant_id=str(raw.get("tenant_id", "default")),
        trace_id=str(raw.get("trace_id", "trace_default")),
        source_connection_id=str(raw.get("source_connection_id", "conn_landis")),
        source_replica_id=str(raw.get("source_replica_id", "replica_default")),
        event_type=str(raw.get("event_type", "POWER_OUTAGE")),
        meter_serial_number=str(raw.get("meter_serial") or raw.get("meter_id", "")),
        service_point_id=str(raw["service_point_id"]) if raw.get("service_point_id") else None,
        event_timestamp=event_dt,
        severity=str(raw.get("severity", "CRITICAL")),
        affected_customers=safe_int(raw.get("affected_customers"), default=1),
        recorded_at=datetime.now(UTC),
    )


# Standard canonical normalizer name
normalize_landis_outage_event = normalize_landis_outage


LANDIS_OUTAGE_EVENTS_TRANSFORMER = TransformerSpec(
    app="landis_gyr_ami",
    entity="outage_events",
    fn=normalize_landis_outage,
    description="Transforms raw Landis+Gyr outage event JSON into CanonicalOutageEventDTO",
)

__all__ = [
    "LANDIS_OUTAGE_EVENTS_TRANSFORMER",
    "normalize_landis_outage",
    "normalize_landis_outage_event",
]
