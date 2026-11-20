"""Landis+Gyr HES interval meter reading connector endpoint."""

from __future__ import annotations

from ip.sdk import ConnectorSpec, RequestBuilder, RequestSpec
from ip.solutions.domains.energy.building_blocks.protocol_headers import build_landis_headers
from ip.solutions.domains.energy.landis.commands import MeterReadingExtractCommand
from ip.solutions.domains.energy.landis.payloads import build_landis_query_payload


def get_landis_meter_readings(cmd: MeterReadingExtractCommand) -> RequestSpec:
    """Pure request builder for Landis+Gyr interval readings. Zero decorators."""
    return (
        RequestBuilder.post("/api/v2/meter-readings/query")
        .with_headers(build_landis_headers())
        .with_body(build_landis_query_payload(cmd))
        .build()
    )


LANDIS_METER_READINGS_CONNECTOR = ConnectorSpec(
    app="landis_gyr_ami",
    entity="meter_readings",
    fn=get_landis_meter_readings,
    description="Builds standard HTTP POST request for Landis+Gyr interval meter readings",
)

__all__ = [
    "LANDIS_METER_READINGS_CONNECTOR",
    "get_landis_meter_readings",
]
