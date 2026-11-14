"""Boundary DTOs and stream translator for Simulator Entities (`ip.simulator_entities`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from ip.solutions.connectors.sandbox.universal.chaos import SimulatorChaosPolicy
from ip.solutions.connectors.sandbox.universal.spec import (
    PushCadenceMode,
    SimulatorStreamSpec,
    StreamVelocityMode,
)
from seedwork.domain.types import JsonDict, JsonValue

SIMULATOR_ENTITY_ID_PREFIX: Final[str] = "sim_ent"


@dataclass(frozen=True)
class SimulatorEntityDTO:
    """1-to-1 immutable boundary DTO for rows in `ip.simulator_entities`."""

    id: str
    tenant_id: str
    connection_id: str
    entity_name: str
    primary_key_field: str
    cursor_field: str
    records_per_pull: int
    cursor_step_seconds: int
    velocity_mode: StreamVelocityMode
    sample_blueprint: JsonValue
    inferred_json_schema: JsonDict
    chaos_policy: JsonDict
    version: int
    created_at: datetime
    updated_at: datetime
    push_mode: PushCadenceMode = PushCadenceMode.RANDOM_BURST
    push_config: JsonDict = field(default_factory=dict)


def entity_dto_to_stream_spec(dto: SimulatorEntityDTO) -> SimulatorStreamSpec:
    """Pure translator converting a persisted `SimulatorEntityDTO` into a `SimulatorStreamSpec`."""
    return SimulatorStreamSpec(
        stream_name=dto.entity_name,
        json_schema=dict(dto.inferred_json_schema),
        primary_key_field=dto.primary_key_field,
        cursor_field=dto.cursor_field,
        velocity_mode=dto.velocity_mode,
        records_per_pull=dto.records_per_pull,
        cursor_step_seconds=dto.cursor_step_seconds,
        chaos_policy=SimulatorChaosPolicy.from_mapping(dto.chaos_policy),
        push_mode=dto.push_mode,
        push_config=dict(dto.push_config),
    )


__all__ = [
    "SIMULATOR_ENTITY_ID_PREFIX",
    "SimulatorEntityDTO",
    "entity_dto_to_stream_spec",
]
