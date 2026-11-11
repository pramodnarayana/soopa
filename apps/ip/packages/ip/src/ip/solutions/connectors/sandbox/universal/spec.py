"""Stream specification and connection scalar configuration value objects for the Universal Schema Simulator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ip.solutions.connectors.sandbox.universal.chaos import SimulatorChaosPolicy
from seedwork.domain.types import JsonDict

UNIVERSAL_SIMULATOR_APP_ID = "universal_simulator"
MAX_SIMULATOR_ENTITIES_PER_CONNECTION = 100
MAX_SAMPLE_BLUEPRINT_BYTES = 262_144
MIN_SIMULATOR_RECORDS_PER_PULL = 1
MAX_SIMULATOR_RECORDS_PER_PULL = 5000
DEFAULT_SIMULATOR_RECORDS_PER_PULL = 25
MIN_SIMULATOR_CURSOR_STEP_SECONDS = 1
MAX_SIMULATOR_CURSOR_STEP_SECONDS = 86400
DEFAULT_SIMULATOR_CURSOR_STEP_SECONDS = 60
MIN_SIMULATED_PUSH_COUNT = 1
MAX_SIMULATED_PUSH_COUNT = 100
DEFAULT_SIMULATED_PUSH_COUNT = 5


class StreamVelocityMode(StrEnum):
    """Ingestion velocity classification for simulated entity streams."""

    ENTITY_TRANSACTIONAL = "ENTITY_TRANSACTIONAL"
    TIMESERIES_COLUMNAR = "TIMESERIES_COLUMNAR"


class SimulatorSubmissionStatus(StrEnum):
    """Canonical acknowledgment status for simulated push and destination write responses."""

    ACCEPTED = "ACCEPTED"


class SimulatorWriteFailureCategory(StrEnum):
    """Strongly-typed failure category classification for simulated L5 destination writes."""

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
    records_per_pull: int = DEFAULT_SIMULATOR_RECORDS_PER_PULL
    cursor_step_seconds: int = DEFAULT_SIMULATOR_CURSOR_STEP_SECONDS
    chaos_policy: SimulatorChaosPolicy = field(default_factory=SimulatorChaosPolicy)


@dataclass(frozen=True)
class SimulatorConnectionConfig:
    """Connection-level scalar synthesis parameters parsed from `Connection.public_config`."""

    seed: int = 42
    default_records_per_pull: int = DEFAULT_SIMULATOR_RECORDS_PER_PULL


__all__ = [
    "DEFAULT_SIMULATED_PUSH_COUNT",
    "DEFAULT_SIMULATOR_CURSOR_STEP_SECONDS",
    "DEFAULT_SIMULATOR_RECORDS_PER_PULL",
    "MAX_SAMPLE_BLUEPRINT_BYTES",
    "MAX_SIMULATED_PUSH_COUNT",
    "MAX_SIMULATOR_CURSOR_STEP_SECONDS",
    "MAX_SIMULATOR_ENTITIES_PER_CONNECTION",
    "MAX_SIMULATOR_RECORDS_PER_PULL",
    "MIN_SIMULATED_PUSH_COUNT",
    "MIN_SIMULATOR_CURSOR_STEP_SECONDS",
    "MIN_SIMULATOR_RECORDS_PER_PULL",
    "UNIVERSAL_SIMULATOR_APP_ID",
    "SimulatorConnectionConfig",
    "SimulatorStreamSpec",
    "SimulatorSubmissionStatus",
    "SimulatorWriteFailureCategory",
    "StreamVelocityMode",
]
