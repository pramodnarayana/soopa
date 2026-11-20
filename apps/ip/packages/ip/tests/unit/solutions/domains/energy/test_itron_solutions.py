"""Unit tests for Itron OpenWay building blocks and connector."""

from ip.solutions.domains.energy.building_blocks.protocol_headers import build_soap_headers
from ip.solutions.domains.energy.building_blocks.soap_envelopes import build_soap_envelope
from ip.solutions.domains.energy.itron.meter_readings import get_itron_meter_readings
from ip.solutions.domains.energy.landis.commands import MeterReadingExtractCommand


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


def test_get_itron_meter_readings_constructs_soap_request_spec() -> None:
    cmd = MeterReadingExtractCommand(
        start_time="2026-10-01T00:00:00Z",
        end_time="2026-10-02T00:00:00Z",
        meter_serials=("ITRON-888",),
    )

    spec = get_itron_meter_readings(cmd)

    assert spec.method == "POST"
    assert spec.path == "/AsynchronousCollection/v1/Extract"
    assert spec.headers["Content-Type"] == "text/xml; charset=utf-8"
    assert isinstance(spec.body, str)
    assert "<DeviceID>ITRON-888</DeviceID>" in spec.body
