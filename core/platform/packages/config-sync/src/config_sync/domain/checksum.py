"""Deterministic canonical SHA-256 checksum utilities for Dynamic Watch integrity verification."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from seedwork.domain.types import JsonDict

from config_sync.domain.dtos import ConfigDeltaEvent, ConfigEntityRecord, ConfigSnapshot

CHECKSUM_PREFIX = "sha256:"


def compute_payload_checksum(payload: JsonDict) -> str:
    """Computes a canonical `sha256:<hex>` digest over a JSON dictionary."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{CHECKSUM_PREFIX}{digest}"


def compute_snapshot_checksum(entities: Sequence[ConfigEntityRecord]) -> str:
    """Computes a canonical `sha256:<hex>` digest over a sorted sequence of snapshot entities."""
    normalized = [
        {
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "tenant_id": e.tenant_id,
            "checksum": e.checksum,
        }
        for e in sorted(entities, key=lambda r: (r.entity_type, r.tenant_id, r.entity_id))
    ]
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{CHECKSUM_PREFIX}{digest}"


def verify_delta_checksum(event: ConfigDeltaEvent) -> bool:
    """Verifies that a streamed delta event's payload matches its declared SHA-256 checksum."""
    return compute_payload_checksum(event.payload) == event.checksum


def verify_snapshot_checksum(snapshot: ConfigSnapshot) -> bool:
    """Verifies that a streamed snapshot's entity list matches its declared SHA-256 checksum."""
    return compute_snapshot_checksum(snapshot.entities) == snapshot.checksum


__all__ = [
    "CHECKSUM_PREFIX",
    "compute_payload_checksum",
    "compute_snapshot_checksum",
    "verify_delta_checksum",
    "verify_snapshot_checksum",
]
