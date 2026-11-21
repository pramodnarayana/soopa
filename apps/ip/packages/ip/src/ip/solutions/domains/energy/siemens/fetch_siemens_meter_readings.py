"""Siemens EnergyIP HES interval meter reading connector endpoint."""

from __future__ import annotations

from ip.sdk import ConnectorSpec, RequestBuilder, RequestSpec
from ip.solutions.domains.energy.commands import MeterReadingExtractCommand
from ip.solutions.domains.energy.siemens.siemens_headers import build_siemens_headers
from ip.solutions.domains.energy.siemens.siemens_payloads import build_siemens_query_payload


def fetch_siemens_meter_readings(cmd: MeterReadingExtractCommand) -> RequestSpec:
    """Pure request builder for Siemens EnergyIP interval readings.

    Constructs a standard REST POST RequestSpec targeting the EnergyIP intervals endpoint.
    Zero decorators, zero network calls, zero database connections.
    """
    return (
        RequestBuilder.post("/energyip/api/v1/meter-readings/intervals")
        .with_headers(build_siemens_headers())
        .with_body(build_siemens_query_payload(cmd))
        .build()
    )


# Alias for backward compatibility and naming symmetry
get_siemens_meter_readings = fetch_siemens_meter_readings


SIEMENS_METER_READINGS_CONNECTOR = ConnectorSpec(
    app="siemens_energyip_ami",
    entity="meter_readings",
    fn=fetch_siemens_meter_readings,
    description="Builds standard HTTP POST request for Siemens EnergyIP interval meter readings",
)

__all__ = [
    "SIEMENS_METER_READINGS_CONNECTOR",
    "fetch_siemens_meter_readings",
    "get_siemens_meter_readings",
]
