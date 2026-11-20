"""Payload serializers for Landis+Gyr Gridstream AMI API operations."""

from __future__ import annotations

from ip.solutions.domains.energy.landis.commands import MeterReadingExtractCommand
from seedwork.domain.types import JsonDict


def build_landis_query_payload(cmd: MeterReadingExtractCommand) -> JsonDict:
    """Builds standard Landis JSON query payload from a strongly-typed command DTO."""
    body: JsonDict = {
        "startTime": cmd.start_time,
        "endTime": cmd.end_time,
        "readingType": cmd.reading_type,
    }
    if cmd.meter_serials:
        body["meterList"] = [s for s in cmd.meter_serials]
    return body
