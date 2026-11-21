"""Landis+Gyr HES power outage events request builder."""

from __future__ import annotations

from ip.sdk import ConnectorSpec, RequestBuilder, RequestSpec
from ip.solutions.domains.energy.building_blocks.query_parameters import build_query_params
from ip.solutions.domains.energy.commands import OutageQueryCommand
from ip.solutions.domains.energy.landis.landis_headers import build_landis_headers


def fetch_landis_outages(cmd: OutageQueryCommand) -> RequestSpec:
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


# Alias for backward compatibility
get_landis_outage_events = fetch_landis_outages
fetch_landis_outage_events = fetch_landis_outages


LANDIS_OUTAGE_EVENTS_CONNECTOR = ConnectorSpec(
    app="landis_gyr_ami",
    entity="outage_events",
    fn=fetch_landis_outages,
    description="Builds standard HTTP GET request with query params for Landis outage events",
)

__all__ = [
    "LANDIS_OUTAGE_EVENTS_CONNECTOR",
    "fetch_landis_outage_events",
    "fetch_landis_outages",
    "get_landis_outage_events",
]
