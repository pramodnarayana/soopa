"""Discovered stream field and schema value objects."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from ip.engine.domain.replication.enums import SyncMode

__all__ = ["StreamField", "StreamSchema", "compute_discovered_streams_hash"]


@dataclass(frozen=True)
class StreamField:
    name: str
    data_type: str
    nullable: bool = True
    description: str | None = None


@dataclass(frozen=True)
class StreamSchema:
    name: str
    fields: Sequence[StreamField]
    primary_key: Sequence[str]
    cursor_field: str | None = None
    supported_sync_modes: Sequence[SyncMode] = (
        SyncMode.FULL_REFRESH,
        SyncMode.INCREMENTAL,
    )


def compute_discovered_streams_hash(streams: Sequence[StreamSchema]) -> str:
    """Computes a deterministic SHA-256 hash over discovered stream schemas."""
    normalized = [
        {
            "name": s.name,
            "primary_key": sorted(s.primary_key),
            "cursor_field": s.cursor_field,
            "supported_sync_modes": sorted(m.value for m in s.supported_sync_modes),
            "fields": sorted(
                (
                    {
                        "name": f.name,
                        "data_type": f.data_type,
                        "nullable": f.nullable,
                    }
                    for f in s.fields
                ),
                key=lambda item: str(item["name"]),
            ),
        }
        for s in sorted(streams, key=lambda item: item.name)
    ]
    serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
