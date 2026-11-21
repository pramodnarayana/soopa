"""Itron OpenWay Collection Engine interval meter reading request builder."""

from __future__ import annotations

from ip.sdk import ConnectorSpec, RequestBuilder, RequestSpec
from ip.solutions.domains.energy.building_blocks.soap_envelopes import build_soap_envelope
from ip.solutions.domains.energy.commands import MeterReadingExtractCommand
from ip.solutions.domains.energy.itron.itron_headers import build_itron_soap_headers
from ip.solutions.domains.energy.itron.itron_payloads import build_itron_extract_payload


def fetch_itron_meter_readings(cmd: MeterReadingExtractCommand) -> RequestSpec:
    """Pure request builder constructing a standard SOAP 1.2 POST request for Itron OpenWay meter extraction.

    Zero decorators, zero network calls, zero database connections.
    """
    soap_body = build_soap_envelope(
        service_namespace="http://itron.com/openway/collection/v1",
        operation_name="ExtractIntervalData",
        payload_xml=build_itron_extract_payload(cmd),
    )

    return (
        RequestBuilder.post("/AsynchronousCollection/v1/Extract")
        .with_headers(build_itron_soap_headers("ExtractIntervalData"))
        .with_body(soap_body)
        .build()
    )


# Alias for backward compatibility
get_itron_meter_readings = fetch_itron_meter_readings


ITRON_METER_READINGS_CONNECTOR = ConnectorSpec(
    app="itron_openway_ami",
    entity="meter_readings",
    fn=fetch_itron_meter_readings,
    description="Builds SOAP 1.2 extract request for Itron OpenWay meter interval readings.",
)

__all__ = [
    "ITRON_METER_READINGS_CONNECTOR",
    "fetch_itron_meter_readings",
    "get_itron_meter_readings",
]
