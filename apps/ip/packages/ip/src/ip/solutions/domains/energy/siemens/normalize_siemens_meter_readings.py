"""Pure functional canonical normalizer for Siemens EnergyIP meter reading records."""

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

SIEMENS_QUALITY_FLAGS: dict[str, str] = {
    "VALID": MeterReadingQualityFlag.VALIDATED.value,
    "OK": MeterReadingQualityFlag.VALIDATED.value,
    "ESTIMATED": MeterReadingQualityFlag.ESTIMATED.value,
    "SUSPECT": MeterReadingQualityFlag.ESTIMATED.value,
    "EST": MeterReadingQualityFlag.ESTIMATED.value,
    "MISSING": MeterReadingQualityFlag.TOMBSTONED.value,
}


def normalize_siemens_meter_reading(
    raw: JsonDict,
    ctx: TransformationContext | None = None,
) -> CanonicalMeterReadingDTO:
    """Pure canonical normalizer mapping raw Siemens EnergyIP JSON into CanonicalMeterReadingDTO.

    Zero decorators, zero database calls, zero external mocks required for testing.
    """
    meter_serial = str(
        raw.get("meter_identifier") or raw.get("meter_id") or raw.get("meter_serial") or ""
    ).strip()
    if not meter_serial:
        raise ValueError("Raw Siemens record missing required meter identifier")

    timestamp_raw = raw.get("interval_end") or raw.get("reading_timestamp") or raw.get("timestamp")
    if not timestamp_raw:
        raise ValueError("Raw Siemens record missing required timestamp")

    reading_dt = parse_iso_datetime(timestamp_raw)

    sp_id_raw = raw.get("service_point_id") or raw.get("premise_id")
    sp_id = str(sp_id_raw).strip() if sp_id_raw is not None and str(sp_id_raw).strip() else None

    # Handle either direct kWh or Wh scaling
    kwh_del = safe_float(raw.get("delivered_kwh") or raw.get("kwh_delivered"))
    if kwh_del == 0.0 and raw.get("import_wh") is not None:
        kwh_del = safe_float(raw.get("import_wh")) / 1000.0

    kwh_rec = safe_float(raw.get("received_kwh") or raw.get("kwh_received"), default=0.0)
    if kwh_rec == 0.0 and raw.get("export_wh") is not None:
        kwh_rec = safe_float(raw.get("export_wh")) / 1000.0

    voltage = safe_float(raw.get("voltage_avg") or raw.get("voltage"))
    voltage_val = voltage if voltage > 0.0 else None

    return CanonicalMeterReadingDTO(
        id=f"reading_siemens_{meter_serial}_{int(reading_dt.timestamp())}",
        tenant_id=str(raw.get("tenant_id", "default")),
        trace_id=str(raw.get("trace_id", "trace_default")),
        source_connection_id=str(raw.get("source_connection_id", "conn_siemens")),
        source_replica_id=str(raw.get("source_replica_id", "replica_default")),
        meter_serial_number=meter_serial,
        service_point_id=sp_id,
        reading_timestamp=reading_dt,
        interval_minutes=safe_int(
            raw.get("interval_length_minutes") or raw.get("interval_minutes"), default=15
        ),
        kwh_delivered=kwh_del,
        kwh_received=kwh_rec,
        voltage_avg=voltage_val,
        quality_flag=map_enum(
            raw.get("status") or raw.get("validation_status"),
            SIEMENS_QUALITY_FLAGS,
            default=MeterReadingQualityFlag.VALIDATED.value,
        ),
        recorded_at=datetime.now(UTC),
    )


# Alias for backward compatibility
normalize_siemens_meter = normalize_siemens_meter_reading


SIEMENS_METER_READINGS_TRANSFORMER = TransformerSpec(
    app="siemens_energyip_ami",
    entity="meter_readings",
    fn=normalize_siemens_meter_reading,
    description="Transforms raw Siemens EnergyIP meter reading JSON/dict into CanonicalMeterReadingDTO.",
)

__all__ = [
    "SIEMENS_METER_READINGS_TRANSFORMER",
    "SIEMENS_QUALITY_FLAGS",
    "normalize_siemens_meter",
    "normalize_siemens_meter_reading",
]
