"""Payload serializers for Itron OpenWay Collection Engine SOAP operations."""

from __future__ import annotations

from xml.sax.saxutils import escape

from ip.solutions.domains.energy.commands import MeterReadingExtractCommand


def build_itron_extract_payload(cmd: MeterReadingExtractCommand) -> str:
    """Builds Itron XML inner payload from strongly-typed extraction command."""
    meters_xml = "".join(f"<DeviceID>{escape(m)}</DeviceID>" for m in cmd.meter_serials)
    return (
        f"<ExtractRequest>"
        f"<StartTime>{cmd.start_time}</StartTime>"
        f"<EndTime>{cmd.end_time}</EndTime>"
        f"<TargetDevices>{meters_xml}</TargetDevices>"
        f"</ExtractRequest>"
    )


__all__ = ["build_itron_extract_payload"]
