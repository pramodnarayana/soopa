"""Port contracts and DTOs for external application connectors.

All types are pure Python @dataclass(frozen=True) instances.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ip.domain.types import JsonDict


@dataclass(frozen=True)
class ConnectionCheckResultDTO:
    """Result of a connection connectivity and health check."""

    success: bool
    status: str  # 'SUCCEEDED' | 'FAILED'
    message: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class StreamFieldDTO:
    name: str
    data_type: str
    nullable: bool = True
    description: str | None = None


@dataclass(frozen=True)
class StreamSchemaDTO:
    name: str
    fields: Sequence[StreamFieldDTO]
    primary_key: Sequence[str]
    cursor_field: str | None = None
    supported_sync_modes: Sequence[str] = ("FULL_REFRESH", "INCREMENTAL")


@dataclass(frozen=True)
class DiscoveredCatalogDTO:
    connection_id: str
    catalog_version: int
    catalog_hash: str
    streams: Sequence[StreamSchemaDTO]
    discovered_at: str


@dataclass(frozen=True)
class RecordEnvelopeDTO:
    """Structured record yielded from a stream during extraction."""

    stream_name: str
    record_id: str
    data: JsonDict
    emitted_at: str  # ISO 8601 UTC


@dataclass(frozen=True)
class WriteRecordCommand:
    """Command to mutate a record in a target external application."""

    stream_name: str
    operation: str  # 'CREATE' | 'UPDATE' | 'UPSERT' | 'DELETE'
    payload: JsonDict
    record_id: str | None = None


@dataclass(frozen=True)
class WriteResultDTO:
    """Outcome of writing a record to a target external application."""

    success: bool
    record_id: str
    destination_id: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class CatalogAppSummaryDTO:
    """Summary representation of a connector catalog application."""

    app_id: str
    display_name: str
    category: str
    auth_type: str
    description: str | None = None
    connector_type: str = "DECLARATIVE_HTTP"
    icon_url: str | None = None


@dataclass(frozen=True)
class AppSpecDTO:
    """Specification schema for dynamic UI configuration form generation."""

    app_id: str
    display_name: str
    auth_type: str
    category: str
    properties: Sequence[JsonDict]
    description: str | None = None
