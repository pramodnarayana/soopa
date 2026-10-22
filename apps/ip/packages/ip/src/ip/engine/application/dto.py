"""Canonical application DTO definitions for the Integration Platform (DTO-First).

All DTOs are pure Python @dataclass(frozen=True) instances.
Pydantic BaseModels and ORM models must NEVER cross into this layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from ip.engine.domain.exceptions import IpError
from ip.engine.domain.models.connection import Connection
from ip.engine.domain.types import JsonDict
from ip.engine.ports.types import (
    AppSpecDTO,
    AppSpecResultDTO,
    CatalogAppSummaryDTO,
    ConnectionCheckResultDTO,
    ConnectorPropertyDTO,
    DiscoveredCatalogDTO,
    DropdownOptionDTO,
    OAuthConfigDTO,
    RecordEnvelopeDTO,
    StreamFieldDTO,
    StreamSchemaDTO,
    WriteRecordCommand,
    WriteResultDTO,
)

__all__ = [
    "AppSpecDTO",
    "AppSpecResultDTO",
    "CatalogAppSummaryDTO",
    "ConnectionCheckResultDTO",
    "ConnectionDTO",
    "ConnectionOperationResultDTO",
    "ConnectorPropertyDTO",
    "DiscoveredCatalogDTO",
    "DropdownOptionDTO",
    "OAuthConfigDTO",
    "RecordEnvelopeDTO",
    "StreamFieldDTO",
    "StreamSchemaDTO",
    "WriteRecordCommand",
    "WriteResultDTO",
]


@dataclass(frozen=True)
class ConnectionOperationResultDTO:
    """Structured result returned by connection lifecycle operations."""

    success: bool
    connection: ConnectionDTO | None = None
    error_code: str | None = None
    error_message: str | None = None
    error: IpError | None = None

    @classmethod
    def ok(cls, connection: ConnectionDTO) -> ConnectionOperationResultDTO:
        return cls(success=True, connection=connection)

    @classmethod
    def from_error(cls, error: IpError) -> ConnectionOperationResultDTO:
        return cls(
            success=False,
            error=error,
            error_code=error.code.value,
            error_message=error.message,
        )


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

    @classmethod
    def from_domain(cls, conn: Connection) -> ConnectionDTO:
        return cls(
            id=conn.id,
            tenant_id=conn.tenant_id,
            app_id=conn.app_id,
            name=conn.name,
            auth_type=conn.auth_type.value,
            public_config=dict(conn.public_config),
            status=conn.status.value,
            connection_fingerprint=conn.connection_fingerprint,
            token_expires_at=conn.token_expires_at,
            last_refreshed_at=conn.last_refreshed_at,
            last_error_code=conn.last_error_code,
            last_error_message=conn.last_error_message,
            created_at=conn.created_at,
            updated_at=conn.updated_at,
            deactivated_at=conn.deactivated_at,
        )
