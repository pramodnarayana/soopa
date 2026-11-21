"""Unit tests for Itron OpenWay building blocks, connector, and normalizer (Zero Mocks)."""

import pytest
from ip.solutions.domains.energy.building_blocks.protocol_headers import build_soap_headers
from ip.solutions.domains.energy.building_blocks.soap_envelopes import build_soap_envelope
from ip.solutions.domains.energy.canonical import MeterReadingQualityFlag
from ip.solutions.domains.energy.commands import MeterReadingExtractCommand
from ip.solutions.domains.energy.itron import (
    ITRON_METER_READINGS_CONNECTOR,
    ITRON_METER_READINGS_TRANSFORMER,
    fetch_itron_meter_readings,
    get_itron_meter_readings,
    normalize_itron_meter_reading,
)
from seedwork.domain.types import JsonDict


def test_build_soap_headers_formats_action() -> None:
    headers = build_soap_headers("ExtractIntervalData")
    assert headers["Content-Type"] == "text/xml; charset=utf-8"
    assert headers["SOAPAction"] == '"ExtractIntervalData"'


def test_build_soap_envelope_wraps_payload() -> None:
    envelope = build_soap_envelope(
        service_namespace="http://example.com/service",
        operation_name="GetData",
        payload_xml="<Param>1</Param>",
    )
    assert "<soapenv:Envelope" in envelope
    assert "<ns:GetData>" in envelope
    assert "<Param>1</Param>" in envelope


def test_fetch_itron_meter_readings_constructs_soap_request_spec() -> None:
    cmd = MeterReadingExtractCommand(
        start_time="2026-10-01T00:00:00Z",
        end_time="2026-10-02T00:00:00Z",
        meter_serials=("ITRON-888",),
    )

    spec = fetch_itron_meter_readings(cmd)

    assert spec.method == "POST"
    assert spec.path == "/AsynchronousCollection/v1/Extract"
    assert spec.headers["Content-Type"] == "text/xml; charset=utf-8"
    assert isinstance(spec.body, str)
    assert "<DeviceID>ITRON-888</DeviceID>" in spec.body

    # Verify alias works identically
    spec_alias = get_itron_meter_readings(cmd)
    assert spec_alias == spec


def test_normalize_itron_meter_reading_pure_transformation() -> None:
    raw: JsonDict = {
        "serial_number": "ITRON-888",
        "last_reading_time": "2026-10-01T15:30:00Z",
        "kwh_delivered": 4.12,
        "kwh_received": 0.05,
        "voltage_avg": 239.8,
        "interval_minutes": 15,
        "quality": "VALIDATED",
        "service_point_id": "SP-999",
        "tenant_id": "tenant_1",
        "trace_id": "trace_xyz",
    }

    dto = normalize_itron_meter_reading(raw)

    assert dto.meter_serial_number == "ITRON-888"
    assert dto.service_point_id == "SP-999"
    assert dto.interval_minutes == 15
    assert dto.kwh_delivered == 4.12
    assert dto.kwh_received == 0.05
    assert dto.voltage_avg == 239.8
    assert dto.quality_flag == MeterReadingQualityFlag.VALIDATED.value
    assert dto.tenant_id == "tenant_1"
    assert dto.trace_id == "trace_xyz"


def test_normalize_itron_meter_reading_rejects_missing_fields() -> None:
    with pytest.raises(ValueError, match="missing required meter identifier"):
        normalize_itron_meter_reading({"last_reading_time": "2026-10-01T15:00:00Z"})

    with pytest.raises(ValueError, match="missing required reading timestamp"):
        normalize_itron_meter_reading({"serial_number": "ITRON-1"})


def test_itron_specs_metadata() -> None:
    assert ITRON_METER_READINGS_CONNECTOR.app == "itron_openway_ami"
    assert ITRON_METER_READINGS_TRANSFORMER.app == "itron_openway_ami"
