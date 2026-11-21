"""Pure functional canonical normalizer for Itron OpenWay / ChoiceConnect AMI meter reading records."""

from __future__ import annotations

from datetime import UTC, datetime

from seedwork.domain.types import JsonDict

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

ITRON_QUALITY_FLAGS: dict[str, str] = {
    "VALIDATED": MeterReadingQualityFlag.VALIDATED.value,
    "OK": MeterReadingQualityFlag.VALIDATED.value,
    "ESTIMATED": MeterReadingQualityFlag.ESTIMATED.value,
    "EST": MeterReadingQualityFlag.ESTIMATED.value,
    "TOMBSTONED": MeterReadingQualityFlag.TOMBSTONED.value,
    "MISSING": MeterReadingQualityFlag.TOMBSTONED.value,
}


def normalize_itron_meter_reading(raw: JsonDict) -> CanonicalMeterReadingDTO:
    """Pure canonical normalizer mapping raw Itron JSON into CanonicalMeterReadingDTO.

    Zero decorators, zero database calls, zero mocks required for testing.
    """
    meter_serial = str(raw.get("serial_number") or raw.get("meter_id") or "").strip()
    if not meter_serial:
        raise ValueError("Raw Itron record missing required meter identifier (serial_number)")

    timestamp_raw = raw.get("last_reading_time") or raw.get("reading_timestamp")
    if not timestamp_raw:
        raise ValueError("Raw Itron record missing required reading timestamp (last_reading_time)")

    reading_dt = parse_iso_datetime(timestamp_raw)

    sp_id_raw = raw.get("service_point_id")
    sp_id = str(sp_id_raw).strip() if sp_id_raw is not None and str(sp_id_raw).strip() else None

    return CanonicalMeterReadingDTO(
        id=f"reading_itron_{meter_serial}_{int(reading_dt.timestamp())}",
        tenant_id=str(raw.get("tenant_id", "default")),
        trace_id=str(raw.get("trace_id", "trace_default")),
        source_connection_id=str(raw.get("source_connection_id", "conn_itron")),
        source_replica_id=str(raw.get("source_replica_id", "replica_default")),
        meter_serial_number=meter_serial,
        service_point_id=sp_id,
        reading_timestamp=reading_dt,
        interval_minutes=safe_int(raw.get("interval_minutes"), default=15),
        kwh_delivered=safe_float(raw.get("kwh_delivered") or raw.get("active_energy_kwh")),
        kwh_received=safe_float(
            raw.get("kwh_received") or raw.get("reverse_energy_kwh"), default=0.0
        ),
        voltage_avg=safe_float(raw.get("voltage_avg") or raw.get("voltage")),
        quality_flag=map_enum(
            raw.get("status") or raw.get("quality_code"),
            ITRON_QUALITY_FLAGS,
            default=MeterReadingQualityFlag.VALIDATED.value,
        ),
        recorded_at=datetime.now(UTC),
    )


# Alias for backward compatibility
normalize_itron_meter = normalize_itron_meter_reading


ITRON_METER_READINGS_TRANSFORMER = TransformerSpec(
    app="itron_openway_ami",
    entity="meter_readings",
    fn=normalize_itron_meter_reading,
    description="Transforms raw Itron OpenWay meter reading JSON/dict into CanonicalMeterReadingDTO.",
)

__all__ = [
    "ITRON_METER_READINGS_TRANSFORMER",
    "ITRON_QUALITY_FLAGS",
    "normalize_itron_meter",
    "normalize_itron_meter_reading",
]
