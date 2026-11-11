"""Chaos fault injection policies and enumerations for the Universal Schema Simulator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from seedwork.domain.types import JsonValue


class SimulatedFaultType(StrEnum):
    """Types of deterministic faults that can be injected by the simulator."""

    NONE = "NONE"
    DUPLICATE = "DUPLICATE"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
    SPIKE_ANOMALY = "SPIKE_ANOMALY"
    HTTP_429 = "HTTP_429"
    HTTP_500 = "HTTP_500"


def _coerce_percentage(raw: JsonValue | None, default: float = 0.0) -> float:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return max(0.0, min(100.0, float(raw)))
    if isinstance(raw, str) and raw.strip():
        try:
            return max(0.0, min(100.0, float(raw.strip())))
        except ValueError:
            return default
    return default


def _coerce_non_negative_int(raw: JsonValue | None, default: int = 0) -> int:
    if isinstance(raw, int) and not isinstance(raw, bool):
        return max(0, raw)
    if isinstance(raw, float):
        return max(0, int(raw))
    if isinstance(raw, str) and raw.strip():
        try:
            return max(0, int(raw.strip()))
        except ValueError:
            return default
    return default


@dataclass(frozen=True)
class SimulatorChaosPolicy:
    """Deterministic chaos injection probabilities (0.0 to 100.0) for QA stress testing."""

    duplicate_rate_percent: float = 0.0
    schema_violation_rate_percent: float = 0.0
    spike_anomaly_rate_percent: float = 0.0
    egress_http_error_rate_percent: float = 0.0
    egress_simulated_latency_ms: int = 0

    @classmethod
    def from_mapping(cls, raw: Mapping[str, JsonValue] | None) -> SimulatorChaosPolicy:
        if raw is None:
            return cls()
        return cls(
            duplicate_rate_percent=_coerce_percentage(raw.get("duplicate_rate_percent")),
            schema_violation_rate_percent=_coerce_percentage(
                raw.get("schema_violation_rate_percent")
            ),
            spike_anomaly_rate_percent=_coerce_percentage(raw.get("spike_anomaly_rate_percent")),
            egress_http_error_rate_percent=_coerce_percentage(
                raw.get("egress_http_error_rate_percent")
            ),
            egress_simulated_latency_ms=_coerce_non_negative_int(
                raw.get("egress_simulated_latency_ms")
            ),
        )


__all__ = [
    "SimulatedFaultType",
    "SimulatorChaosPolicy",
]
