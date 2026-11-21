"""Pure payload builders for Siemens EnergyIP HES API queries."""

from __future__ import annotations

from seedwork.domain.types import JsonDict

from ip.solutions.domains.energy.commands import MeterReadingExtractCommand


def build_siemens_query_payload(cmd: MeterReadingExtractCommand) -> JsonDict:
    """Builds the canonical JSON payload for Siemens EnergyIP interval extractions.

    Siemens EnergyIP expects ISO 8601 UTC timestamps, an interval duration (e.g. 15 minutes),
    standard IEC/OBIS reading types, and an optional list of meter identifiers.
    Zero decorators, zero I/O.
    """
    payload: JsonDict = {
        "startDateTime": cmd.start_time,
        "endDateTime": cmd.end_time,
        "intervalLength": 15,
        "readingTypes": ["1.0.1.8.0.255", "1.0.2.8.0.255"],
        "unitOfMeasure": "KWH",
    }
    if cmd.meter_serials:
        payload["meterIdentifiers"] = list(cmd.meter_serials)

    return payload


__all__ = [
    "build_siemens_query_payload",
]
