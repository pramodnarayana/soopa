"""Co-located Command DTOs for Energy AMI HES extraction requests (Vendor-Agnostic)."""

from __future__ import annotations

from dataclasses import dataclass

from seedwork.domain.types import JsonDict


@dataclass(frozen=True, kw_only=True)
class MeterReadingExtractCommand:
    """Co-located Command DTO for interval meter reading extractions."""

    start_time: str
    end_time: str
    meter_serials: tuple[str, ...] = ()
    reading_type: str = "15_MIN_INTERVAL"

    @classmethod
    def from_payload(cls, payload: JsonDict) -> MeterReadingExtractCommand:
        serials_raw = payload.get("meter_serials")
        serials: tuple[str, ...] = ()
        if isinstance(serials_raw, list):
            serials = tuple(str(s) for s in serials_raw)

        return cls(
            start_time=str(payload["start_time"]),
            end_time=str(payload["end_time"]),
            meter_serials=serials,
            reading_type=str(payload.get("reading_type", "15_MIN_INTERVAL")),
        )


@dataclass(frozen=True, kw_only=True)
class OutageQueryCommand:
    """Co-located Command DTO for power outage event queries."""

    from_timestamp: str
    to_timestamp: str
    severity: str = "CRITICAL"
    meter_serials: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, payload: JsonDict) -> OutageQueryCommand:
        serials_raw = payload.get("meter_serials")
        serials: tuple[str, ...] = ()
        if isinstance(serials_raw, list):
            serials = tuple(str(s) for s in serials_raw)

        from_ts = str(payload.get("from_timestamp") or payload.get("start_time") or "")
        to_ts = str(payload.get("to_timestamp") or payload.get("end_time") or "")

        return cls(
            from_timestamp=from_ts,
            to_timestamp=to_ts,
            severity=str(payload.get("severity", "CRITICAL")),
            meter_serials=serials,
        )


__all__ = [
    "MeterReadingExtractCommand",
    "OutageQueryCommand",
]
