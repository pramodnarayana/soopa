"""Discovered stream field and schema value objects."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ip.engine.domain.replication.enums import SyncMode

__all__ = ["StreamField", "StreamSchema"]


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
