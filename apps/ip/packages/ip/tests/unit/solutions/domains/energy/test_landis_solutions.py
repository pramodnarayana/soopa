"""Unit tests for Landis+Gyr building blocks, connectors, and normalizers."""

from datetime import UTC

import pytest
from ip.solutions.domains.energy.canonical import MeterReadingQualityFlag
from ip.solutions.domains.energy.commands import (
    MeterReadingExtractCommand,
    OutageQueryCommand,
)
from ip.solutions.domains.energy.landis import (
    build_landis_headers,
    build_landis_query_payload,
    fetch_landis_meter_readings,
    get_landis_meter_readings,
    get_landis_outage_events,
    normalize_landis_meter,
    normalize_landis_meter_reading,
)
from seedwork.domain.types import JsonDict


def test_build_landis_headers_includes_required_protocol_keys() -> None:
    headers = build_landis_headers(api_version="v2")

    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"
    assert headers["X-API-Version"] == "v2"
    assert headers["X-Client-System"] == "SOOPA-IP"


def test_build_landis_query_payload_formats_dates_with_meter_list() -> None:
    cmd = MeterReadingExtractCommand(
        start_time="2026-10-01T00:00:00Z",
        end_time="2026-10-02T00:00:00Z",
        meter_serials=("MTR-001", "MTR-002"),
        reading_type="15_MIN_INTERVAL",
    )

    payload = build_landis_query_payload(cmd)

    assert payload["startTime"] == "2026-10-01T00:00:00Z"
    assert payload["endTime"] == "2026-10-02T00:00:00Z"
    assert payload["readingType"] == "15_MIN_INTERVAL"
    assert payload["meterList"] == ["MTR-001", "MTR-002"]


def test_get_landis_meter_readings_constructs_post_request_spec() -> None:
    cmd = MeterReadingExtractCommand(
        start_time="2026-10-01T00:00:00Z",
        end_time="2026-10-02T00:00:00Z",
        meter_serials=("MTR-001",),
    )

    spec = get_landis_meter_readings(cmd)

    assert spec.method == "POST"
    assert spec.path == "/api/v2/meter-readings/query"
    assert spec.headers["X-API-Version"] == "v2"
    assert isinstance(spec.body, dict)
    assert spec.body["meterList"] == ["MTR-001"]

    # Verify fetch_landis_meter_readings alias produces identical RequestSpec
    spec_fetch = fetch_landis_meter_readings(cmd)
    assert spec_fetch == spec


def test_get_landis_outage_events_constructs_get_request_spec() -> None:
    cmd = OutageQueryCommand(
        from_timestamp="2026-10-01T00:00:00Z",
        to_timestamp="2026-10-02T00:00:00Z",
        severity="CRITICAL",
        meter_serials=("MTR-001",),
    )

    spec = get_landis_outage_events(cmd)

    assert spec.method == "GET"
    assert spec.path == "/api/v2/events/outages"
    assert spec.params["fromTimestamp"] == "2026-10-01T00:00:00Z"
    assert spec.params["toTimestamp"] == "2026-10-02T00:00:00Z"
    assert spec.params["severity"] == "CRITICAL"
    assert spec.params["meterList"] == "MTR-001"


def test_normalize_landis_meter_maps_valid_reading() -> None:
    raw: JsonDict = {
        "meter_id": "MTR-BESCOM-001",
        "read_time": "2026-10-01T10:15:00+00:00",
        "active_energy_kwh": "12.450",
        "reverse_energy_kwh": "0.120",
        "voltage": "230.5",
        "status": "OK",
        "interval_minutes": 15,
    }

    dto = normalize_landis_meter(raw)

    assert dto.meter_serial_number == "MTR-BESCOM-001"
    assert dto.reading_timestamp.year == 2026
    assert dto.reading_timestamp.month == 10
    assert dto.reading_timestamp.tzinfo == UTC
    assert dto.kwh_delivered == 12.450
    assert dto.kwh_received == 0.120
    assert dto.voltage_avg == 230.5
    assert dto.quality_flag == MeterReadingQualityFlag.VALIDATED.value

    # Verify normalize_landis_meter_reading alias is the exact same pure function
    assert normalize_landis_meter_reading is normalize_landis_meter


def test_normalize_landis_meter_rejects_missing_identifier() -> None:
    raw: JsonDict = {
        "read_time": "2026-10-01T10:15:00+00:00",
        "active_energy_kwh": "5.0",
    }

    with pytest.raises(ValueError, match="missing required meter identifier"):
        normalize_landis_meter(raw)
