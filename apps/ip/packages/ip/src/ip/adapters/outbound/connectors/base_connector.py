import hashlib
import json
from abc import ABC
from collections.abc import Sequence
from datetime import UTC, datetime

from ip.application.responses import (
    DiscoveredCatalogDTO,
    StreamSchemaDTO,
)
from ip.ports.outbound.connector_port import ConnectorPort


class BaseConnector(ConnectorPort, ABC):
    """Abstract base connector encapsulating catalog hashing and shared helpers."""

    @staticmethod
    def build_catalog_dto(
        connection_id: str,
        streams: Sequence[StreamSchemaDTO],
        catalog_version: int = 1,
        discovered_at: str | None = None,
    ) -> DiscoveredCatalogDTO:
        """Helper to construct DiscoveredCatalogDTO with deterministic SHA-256 hash."""
        stream_dicts = [
            {
                "name": s.name,
                "fields": [{"name": f.name, "type": f.data_type} for f in s.fields],
                "primary_key": list(s.primary_key),
                "cursor_field": s.cursor_field,
            }
            for s in streams
        ]
        raw = json.dumps(stream_dicts, sort_keys=True)
        catalog_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        return DiscoveredCatalogDTO(
            connection_id=connection_id,
            catalog_version=catalog_version,
            catalog_hash=catalog_hash,
            streams=streams,
            discovered_at=discovered_at or datetime.now(UTC).isoformat(),
        )
