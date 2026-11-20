"""Landis+Gyr HES power outage events connector endpoint."""

from __future__ import annotations

from ip.sdk import ConnectorSpec, RequestBuilder, RequestSpec
from ip.solutions.domains.energy.building_blocks.protocol_headers import build_landis_headers
from ip.solutions.domains.energy.building_blocks.query_parameters import build_query_params
from ip.solutions.domains.energy.landis.commands import OutageQueryCommand


def get_landis_outage_events(cmd: OutageQueryCommand) -> RequestSpec:
    """Builds a standard HTTP GET request with query parameters for Landis outage events. Zero decorators."""
    params = build_query_params(
        {
            "fromTimestamp": cmd.from_timestamp,
            "toTimestamp": cmd.to_timestamp,
            "severity": cmd.severity,
            "meterList": ",".join(cmd.meter_serials) if cmd.meter_serials else None,
        }
    )

    return (
        RequestBuilder.get("/api/v2/events/outages")
        .with_headers(build_landis_headers())
        .with_params(params)
        .build()
    )


LANDIS_OUTAGE_EVENTS_CONNECTOR = ConnectorSpec(
    app="landis_gyr_ami",
    entity="outage_events",
    fn=get_landis_outage_events,
    description="Builds standard HTTP GET request with query params for Landis outage events",
)

__all__ = [
    "LANDIS_OUTAGE_EVENTS_CONNECTOR",
    "get_landis_outage_events",
]
