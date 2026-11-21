"""Unit tests for Siemens EnergyIP pure building blocks, connectors, and normalizers (Zero Mocks)."""

import pytest
from ip.solutions.domains.energy.building_blocks.protocol_headers import build_siemens_headers
from ip.solutions.domains.energy.canonical import MeterReadingQualityFlag
from ip.solutions.domains.energy.commands import MeterReadingExtractCommand
from ip.solutions.domains.energy.siemens import (
    SIEMENS_METER_READINGS_CONNECTOR,
    SIEMENS_METER_READINGS_TRANSFORMER,
    build_siemens_query_payload,
    fetch_siemens_meter_readings,
    get_siemens_meter_readings,
    normalize_siemens_meter_reading,
)
from seedwork.domain.types import JsonDict


def test_build_siemens_headers_formats_version_system() -> None:
    headers = build_siemens_headers(api_version="v1")
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "application/json"
    assert headers["X-EnergyIP-Version"] == "v1"
    assert headers["X-Client-System"] == "SOOPA-IP"


def test_build_siemens_query_payload_constructs_valid_json() -> None:
    cmd = MeterReadingExtractCommand(
        start_time="2026-10-01T00:00:00Z",
        end_time="2026-10-02T00:00:00Z",
        meter_serials=("SIEMENS-101", "SIEMENS-102"),
    )

    payload = build_siemens_query_payload(cmd)
    assert payload["startDateTime"] == "2026-10-01T00:00:00Z"
    assert payload["endDateTime"] == "2026-10-02T00:00:00Z"
    assert payload["intervalLength"] == 15
    assert payload["readingTypes"] == ["1.0.1.8.0.255", "1.0.2.8.0.255"]
    assert payload["meterIdentifiers"] == ["SIEMENS-101", "SIEMENS-102"]


def test_fetch_siemens_meter_readings_constructs_post_request_spec() -> None:
    cmd = MeterReadingExtractCommand(
        start_time="2026-10-01T00:00:00Z",
        end_time="2026-10-02T00:00:00Z",
        meter_serials=("SIEMENS-999",),
    )

    spec = fetch_siemens_meter_readings(cmd)

    assert spec.method == "POST"
    assert spec.path == "/energyip/api/v1/meter-readings/intervals"
    assert spec.headers["X-EnergyIP-Version"] == "v1"
    assert isinstance(spec.body, dict)
    assert spec.body["meterIdentifiers"] == ["SIEMENS-999"]

    # Verify alias works identically
    spec_alias = get_siemens_meter_readings(cmd)
    assert spec_alias == spec


def test_normalize_siemens_meter_reading_pure_transformation() -> None:
    raw: JsonDict = {
        "meter_identifier": "SIEMENS-001",
        "interval_end": "2026-10-01T12:15:00Z",
        "delivered_kwh": 3.75,
        "received_kwh": 0.25,
        "voltage": 240.2,
        "interval_length": 15,
        "quality": "VALID",
        "service_point_id": "SP-88219",
        "tenant_id": "tenant_grid",
        "trace_id": "trace_abc",
    }

    dto = normalize_siemens_meter_reading(raw)

    assert dto.meter_serial_number == "SIEMENS-001"
    assert dto.service_point_id == "SP-88219"
    assert dto.interval_minutes == 15
    assert dto.kwh_delivered == 3.75
    assert dto.kwh_received == 0.25
    assert dto.voltage_avg == 240.2
    assert dto.quality_flag == MeterReadingQualityFlag.VALIDATED.value
    assert dto.tenant_id == "tenant_grid"
    assert dto.trace_id == "trace_abc"


def test_normalize_siemens_meter_reading_converts_wh_to_kwh() -> None:
    raw: JsonDict = {
        "meter_id": "SIEMENS-002",
        "timestamp": "2026-10-01T12:30:00Z",
        "import_wh": 5000,
        "export_wh": 1000,
        "status": "ESTIMATED",
    }

    dto = normalize_siemens_meter_reading(raw)
    assert dto.meter_serial_number == "SIEMENS-002"
    assert dto.kwh_delivered == 5.0
    assert dto.kwh_received == 1.0
    assert dto.quality_flag == MeterReadingQualityFlag.ESTIMATED.value


def test_normalize_siemens_meter_reading_rejects_missing_meter_or_timestamp() -> None:
    with pytest.raises(ValueError, match="missing required meter identifier"):
        normalize_siemens_meter_reading({"interval_end": "2026-10-01T12:00:00Z"})

    with pytest.raises(ValueError, match="missing required timestamp"):
        normalize_siemens_meter_reading({"meter_identifier": "MTR-1"})


def test_siemens_specs_metadata() -> None:
    assert SIEMENS_METER_READINGS_CONNECTOR.app == "siemens_energyip_ami"
    assert SIEMENS_METER_READINGS_CONNECTOR.entity == "meter_readings"
    assert SIEMENS_METER_READINGS_TRANSFORMER.app == "siemens_energyip_ami"
    assert SIEMENS_METER_READINGS_TRANSFORMER.entity == "meter_readings"
