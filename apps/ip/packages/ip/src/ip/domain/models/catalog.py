"""Catalog and Stream definitions representing discovered schemas for connections."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar

from ip.domain.constants import IpDomainIdPrefix
from seedwork.models import AggregateRoot


class SyncMode(StrEnum):
    FULL_REFRESH = "FULL_REFRESH"
    INCREMENTAL = "INCREMENTAL"


@dataclass(frozen=True)
class StreamField:
    name: str
    data_type: str  # e.g., 'string', 'number', 'boolean', 'datetime', 'json'
    nullable: bool = True
    description: str | None = None


@dataclass(frozen=True)
class StreamSchema:
    name: str  # e.g., 'meters', 'usage_points', 'interval_reads'
    fields: Sequence[StreamField]
    primary_key: Sequence[str]
    cursor_field: str | None = None
    supported_sync_modes: Sequence[SyncMode] = (
        SyncMode.FULL_REFRESH,
        SyncMode.INCREMENTAL,
    )


@dataclass(kw_only=True, eq=False)
class ConnectionCatalog(AggregateRoot):
    """Aggregate Root representing the discovered schema definition for a connection."""

    ID_PREFIX: ClassVar[str] = IpDomainIdPrefix.CATALOG

    id: str
    connection_id: str
    catalog_version: int
    catalog_hash: str
    streams: Sequence[StreamSchema]
    is_active: bool = True
    discovered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def create(
        cls,
        *,
        connection_id: str,
        catalog_version: int,
        streams: Sequence[StreamSchema],
    ) -> ConnectionCatalog:
        """Factory method to create a new ConnectionCatalog aggregate."""
        if not connection_id.strip():
            raise ValueError("connection_id cannot be empty")

        # Compute deterministic catalog hash for schema drift detection
        stream_dicts = [
            {
                "name": s.name,
                "fields": [{"name": f.name, "type": f.data_type} for f in s.fields],
                "primary_key": list(s.primary_key),
                "cursor_field": s.cursor_field,
            }
            for s in streams
        ]
        raw_json = json.dumps(stream_dicts, sort_keys=True)
        catalog_hash = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

        return cls(
            id=cls.new_id(),
            connection_id=connection_id,
            catalog_version=catalog_version,
            catalog_hash=catalog_hash,
            streams=streams,
            is_active=True,
        )

    def get_stream(self, stream_name: str) -> StreamSchema | None:
        """Retrieves a stream schema by name."""
        for s in self.streams:
            if s.name == stream_name:
                return s
        return None
