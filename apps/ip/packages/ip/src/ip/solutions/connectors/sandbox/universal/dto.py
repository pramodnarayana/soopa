"""Boundary DTOs and cryptographic key helpers for Virtual Sandboxes (`ip.simulator_sandboxes` & `ip.simulator_entities`)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from ip.solutions.connectors.sandbox.universal.chaos import SimulatorChaosPolicy
from ip.solutions.connectors.sandbox.universal.spec import (
    SimulatorStreamSpec,
    StreamVelocityMode,
)
from seedwork.domain.types import JsonDict, JsonValue

SIMULATOR_SANDBOX_ID_PREFIX: Final[str] = "sbx"
SIMULATOR_API_KEY_PREFIX: Final[str] = "sbx_key_"
SIMULATOR_ENTITY_ID_PREFIX: Final[str] = "sim_ent"


def generate_sandbox_api_key() -> tuple[str, str, str]:
    """Generates a cryptographically random sandbox API key, its SHA-256 hash, and its display prefix."""
    raw_key = f"{SIMULATOR_API_KEY_PREFIX}{secrets.token_hex(24)}"
    key_hash = hash_sandbox_api_key(raw_key)
    key_prefix = raw_key[:16]
    return raw_key, key_hash, key_prefix


def hash_sandbox_api_key(raw_api_key: str) -> str:
    """Computes the SHA-256 hex digest of a sandbox API key."""
    return hashlib.sha256(raw_api_key.strip().encode("utf-8")).hexdigest()


def verify_sandbox_api_key(raw_api_key: str, expected_hash: str) -> bool:
    """Verifies a plaintext sandbox API key against an expected SHA-256 hex digest in constant time."""
    cleaned = raw_api_key.strip()
    if not cleaned or not expected_hash:
        return False
    actual_hash = hash_sandbox_api_key(cleaned)
    return hmac.compare_digest(actual_hash, expected_hash)


@dataclass(frozen=True)
class SimulatorSandboxDTO:
    """1-to-1 immutable boundary DTO for rows in `ip.simulator_sandboxes`."""

    id: str
    tenant_id: str
    name: str
    api_key_hash: str
    api_key_prefix: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SimulatorEntityDTO:
    """1-to-1 immutable boundary DTO for rows in `ip.simulator_entities`."""

    id: str
    tenant_id: str
    sandbox_id: str
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
    )


__all__ = [
    "SIMULATOR_API_KEY_PREFIX",
    "SIMULATOR_ENTITY_ID_PREFIX",
    "SIMULATOR_SANDBOX_ID_PREFIX",
    "SimulatorEntityDTO",
    "SimulatorSandboxDTO",
    "entity_dto_to_stream_spec",
    "generate_sandbox_api_key",
    "hash_sandbox_api_key",
    "verify_sandbox_api_key",
]
