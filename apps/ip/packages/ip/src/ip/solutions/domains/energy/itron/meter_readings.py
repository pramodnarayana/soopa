"""Itron OpenWay Collection Engine interval meter reading connector endpoint."""

from __future__ import annotations

from ip.sdk import ConnectorSpec, RequestBuilder, RequestSpec
from ip.solutions.domains.energy.building_blocks.protocol_headers import build_soap_headers
from ip.solutions.domains.energy.building_blocks.soap_envelopes import build_soap_envelope
from ip.solutions.domains.energy.itron.payloads import build_itron_extract_payload
from ip.solutions.domains.energy.landis.commands import MeterReadingExtractCommand


def get_itron_meter_readings(cmd: MeterReadingExtractCommand) -> RequestSpec:
    """Builds a standard SOAP 1.2 POST request for Itron OpenWay meter extraction."""
    soap_body = build_soap_envelope(
        service_namespace="http://itron.com/openway/collection/v1",
        operation_name="ExtractIntervalData",
        payload_xml=build_itron_extract_payload(cmd),
    )

    return (
        RequestBuilder.post("/AsynchronousCollection/v1/Extract")
        .with_headers(build_soap_headers("ExtractIntervalData"))
        .with_body(soap_body)
        .build()
    )


ITRON_METER_READINGS_CONNECTOR = ConnectorSpec(
    app="itron_openway_ami",
    entity="meter_readings",
    fn=get_itron_meter_readings,
    description="Builds SOAP 1.2 extract request for Itron OpenWay meter interval readings.",
)

__all__ = [
    "ITRON_METER_READINGS_CONNECTOR",
    "get_itron_meter_readings",
]
