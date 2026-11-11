"""Stream specification and manifest value objects for the Universal Schema Simulator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from ip.solutions.connectors.sandbox.universal.chaos import SimulatorChaosPolicy
from seedwork.domain.types import JsonDict


class StreamVelocityMode(StrEnum):
    """Ingestion velocity classification for simulated entity streams."""

    ENTITY_TRANSACTIONAL = "ENTITY_TRANSACTIONAL"
    TIMESERIES_COLUMNAR = "TIMESERIES_COLUMNAR"


@dataclass(frozen=True)
class SimulatorStreamSpec:
    """User-defined JSON Schema stream specification for the Universal Simulator."""

    stream_name: str
    json_schema: JsonDict
    primary_key_field: str = "id"
    cursor_field: str = "updated_at"
    velocity_mode: StreamVelocityMode = StreamVelocityMode.ENTITY_TRANSACTIONAL
    records_per_pull: int = 25
    cursor_step_seconds: int = 60
    chaos_policy: SimulatorChaosPolicy = field(default_factory=SimulatorChaosPolicy)


@dataclass(frozen=True)
class SimulatorManifest:
    """Parsed configuration manifest attached to a Universal Simulator connection's `public_config`."""

    seed: int = 42
    streams: Mapping[str, SimulatorStreamSpec] = field(default_factory=dict)


__all__ = [
    "SimulatorManifest",
    "SimulatorStreamSpec",
    "StreamVelocityMode",
]
