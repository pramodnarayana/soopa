"""Strict boundary response and read DTOs for the Integration Platform.

All DTOs are pure Python @dataclass(frozen=True) instances.
Pydantic BaseModels and ORM models must NEVER cross into this layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from ip.domain.types import JsonDict
from ip.ports.types import (
    ConnectionCheckResultDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    StreamFieldDTO,
    StreamSchemaDTO,
    WriteRecordCommand,
    WriteResultDTO,
)

__all__ = [
    "ConnectionCheckResultDTO",
    "ConnectionDTO",
    "DiscoveredCatalogDTO",
    "RecordEnvelopeDTO",
    "StreamFieldDTO",
    "StreamSchemaDTO",
    "WriteRecordCommand",
    "WriteResultDTO",
]


@dataclass(frozen=True)
class ConnectionDTO:
    """Safe, read-only representation of a connection for boundaries."""

    id: str
    tenant_id: str
    app_id: str
    name: str
    auth_type: str
    public_config: JsonDict
    status: str
    connection_fingerprint: str
    token_expires_at: str | None
    last_refreshed_at: str | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: str
    updated_at: str
    deactivated_at: str | None
