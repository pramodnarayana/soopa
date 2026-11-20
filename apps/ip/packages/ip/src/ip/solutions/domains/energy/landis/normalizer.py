"""Pure functional canonical normalizer for Landis+Gyr meter reading records."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.sdk import (
    TransformerSpec,
    map_enum,
    parse_iso_datetime,
    safe_float,
    safe_int,
)
from ip.solutions.domains.energy.canonical import (
    CanonicalMeterReadingDTO,
    MeterReadingQualityFlag,
)
from seedwork.domain.types import JsonDict

LANDIS_QUALITY_FLAGS: dict[str, str] = {
    "OK": MeterReadingQualityFlag.VALIDATED.value,
    "EST": MeterReadingQualityFlag.ESTIMATED.value,
    "MISSING": MeterReadingQualityFlag.TOMBSTONED.value,
}


def normalize_landis_meter(raw: JsonDict) -> CanonicalMeterReadingDTO:
    """Pure canonical normalizer mapping raw Landis JSON into CanonicalMeterReadingDTO.

    Zero decorators. Zero database calls. Zero external mocks required for testing.
    """
    meter_serial = str(raw.get("meter_id") or raw.get("meter_serial") or "").strip()
    if not meter_serial:
        raise ValueError("Raw Landis record missing required meter identifier")

    timestamp_raw = raw.get("read_time") or raw.get("reading_timestamp")
    reading_dt = parse_iso_datetime(timestamp_raw)

    return CanonicalMeterReadingDTO(
        id=f"reading_{meter_serial}_{int(reading_dt.timestamp())}",
        tenant_id=str(raw.get("tenant_id", "default")),
        trace_id=str(raw.get("trace_id", "trace_default")),
        source_connection_id=str(raw.get("source_connection_id", "conn_landis")),
        source_replica_id=str(raw.get("source_replica_id", "replica_default")),
        meter_serial_number=meter_serial,
        service_point_id=str(raw["service_point_id"]) if raw.get("service_point_id") else None,
        reading_timestamp=reading_dt,
        interval_minutes=safe_int(raw.get("interval_minutes"), default=15),
        kwh_delivered=safe_float(raw.get("active_energy_kwh") or raw.get("kwh_delivered")),
        kwh_received=safe_float(
            raw.get("reverse_energy_kwh") or raw.get("kwh_received"), default=0.0
        ),
        voltage_avg=safe_float(raw["voltage"])
        if "voltage" in raw and raw["voltage"] is not None
        else None,
        quality_flag=map_enum(
            raw.get("status"), LANDIS_QUALITY_FLAGS, default=MeterReadingQualityFlag.ESTIMATED.value
        ),
        recorded_at=datetime.now(UTC),
    )


LANDIS_METER_TRANSFORMER = TransformerSpec(
    app="landis_gyr_ami",
    entity="meter_readings",
    fn=normalize_landis_meter,
    description="Transforms raw Landis+Gyr meter reading records into CanonicalMeterReadingDTO.",
)

__all__ = [
    "LANDIS_METER_TRANSFORMER",
    "LANDIS_QUALITY_FLAGS",
    "normalize_landis_meter",
]
