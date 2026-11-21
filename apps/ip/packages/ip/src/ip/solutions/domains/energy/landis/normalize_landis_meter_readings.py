"""Pure functional canonical normalizer for Landis+Gyr meter reading records."""

from __future__ import annotations

from datetime import UTC, datetime

from seedwork.domain.types import JsonDict

from ip.engine.domain.normalization.dtos import TransformationContext
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

LANDIS_QUALITY_FLAGS: dict[str, str] = {
    "OK": MeterReadingQualityFlag.VALIDATED.value,
    "EST": MeterReadingQualityFlag.ESTIMATED.value,
    "MISSING": MeterReadingQualityFlag.TOMBSTONED.value,
}


def normalize_landis_meter(
    raw: JsonDict,
    ctx: TransformationContext | None = None,
) -> CanonicalMeterReadingDTO:
    """Pure canonical normalizer mapping raw Landis JSON into CanonicalMeterReadingDTO.

    Zero decorators. Zero database calls. Zero external mocks required for testing.
    """
    meter_serial = str(
        raw.get("meter_id") or raw.get("meter_serial") or raw.get("meter_serial_number") or ""
    ).strip()
    if not meter_serial:
        raise ValueError("Raw Landis record missing required meter identifier")

    timestamp_raw = (
        raw.get("read_time")
        or raw.get("reading_timestamp")
        or raw.get("timestamp")
        or raw.get("interval_end_utc")
    )
    reading_dt = parse_iso_datetime(timestamp_raw)

    tenant_id = (
        str(raw.get("tenant_id")) if raw.get("tenant_id") else (ctx.tenant_id if ctx else "default")
    )
    trace_id = (
        str(raw.get("trace_id"))
        if raw.get("trace_id")
        else (ctx.trace_id if ctx else "trace_default")
    )
    source_conn = (
        str(raw.get("source_connection_id"))
        if raw.get("source_connection_id")
        else (ctx.connection_id if ctx else "conn_landis")
    )

    return CanonicalMeterReadingDTO(
        id=f"reading_{meter_serial}_{int(reading_dt.timestamp())}",
        tenant_id=tenant_id,
        trace_id=trace_id,
        source_connection_id=source_conn,
        source_replica_id=str(raw.get("source_replica_id", "replica_default")),
        meter_serial_number=meter_serial,
        service_point_id=str(raw["service_point_id"]) if raw.get("service_point_id") else None,
        reading_timestamp=reading_dt,
        interval_minutes=safe_int(raw.get("interval_minutes"), default=15),
        kwh_delivered=safe_float(
            raw.get("active_energy_kwh") or raw.get("kwh_delivered") or raw.get("energy_kwh")
        ),
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


# Standard canonical normalizer name
normalize_landis_meter_reading = normalize_landis_meter


LANDIS_METER_READINGS_TRANSFORMER = TransformerSpec(
    app="landis_gyr_ami",
    entity="meter_readings",
    fn=normalize_landis_meter_reading,
    description="Transforms raw Landis+Gyr meter reading JSON into CanonicalMeterReadingDTO",
)

__all__ = [
    "LANDIS_METER_READINGS_TRANSFORMER",
    "LANDIS_QUALITY_FLAGS",
    "normalize_landis_meter",
    "normalize_landis_meter_reading",
]
