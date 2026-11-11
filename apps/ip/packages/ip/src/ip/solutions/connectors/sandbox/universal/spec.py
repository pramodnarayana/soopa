"""Stream specification and connection scalar configuration value objects for the Universal Schema Simulator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ip.solutions.connectors.sandbox.universal.chaos import SimulatorChaosPolicy
from seedwork.domain.types import JsonDict

UNIVERSAL_SIMULATOR_APP_ID = "universal_simulator"
MAX_SIMULATOR_ENTITIES_PER_SANDBOX = 100
MAX_SAMPLE_BLUEPRINT_BYTES = 262_144


class StreamVelocityMode(StrEnum):
    """Ingestion velocity classification for simulated entity streams."""

    ENTITY_TRANSACTIONAL = "ENTITY_TRANSACTIONAL"
    TIMESERIES_COLUMNAR = "TIMESERIES_COLUMNAR"


class SimulatorSubmissionStatus(StrEnum):
    """Canonical acknowledgment status for simulated push and destination write responses."""

    ACCEPTED = "ACCEPTED"


class SimulatorWriteFailureCategory(StrEnum):
    """Strongly-typed failure category classification for simulated L5 destination writes."""

    AUTH_ERROR = "AUTH_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"


@dataclass(frozen=True)
class SimulatorStreamSpec:
    """Inferred JSON Schema stream specification used by the synthesizer and catalog extractor."""

    stream_name: str
    json_schema: JsonDict
    primary_key_field: str = "id"
    cursor_field: str = "updated_at"
    velocity_mode: StreamVelocityMode = StreamVelocityMode.ENTITY_TRANSACTIONAL
    records_per_pull: int = 25
    cursor_step_seconds: int = 60
    chaos_policy: SimulatorChaosPolicy = field(default_factory=SimulatorChaosPolicy)


@dataclass(frozen=True)
class SimulatorConnectionConfig:
    """Connection-level parameters stored in `ip.connections.public_config`."""

    sandbox_id: str
    seed: int = 42
    default_records_per_pull: int = 25


__all__ = [
    "MAX_SAMPLE_BLUEPRINT_BYTES",
    "MAX_SIMULATOR_ENTITIES_PER_SANDBOX",
    "UNIVERSAL_SIMULATOR_APP_ID",
    "SimulatorConnectionConfig",
    "SimulatorStreamSpec",
    "SimulatorSubmissionStatus",
    "SimulatorWriteFailureCategory",
    "StreamVelocityMode",
]
