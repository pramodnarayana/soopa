"""Port contracts and DTOs for external application connectors.

All types are pure Python @dataclass(frozen=True) instances.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from seedwork.domain.types import JsonDict

from ip.engine.domain.exceptions import IpError


@dataclass(frozen=True)
class ConnectionCheckResultDTO:
    """Result of a connection connectivity and health check."""

    success: bool
    status: str  # 'SUCCEEDED' | 'FAILED'
    message: str | None = None
    error_code: str | None = None
    error: IpError | None = None

    @classmethod
    def ok(cls, message: str) -> ConnectionCheckResultDTO:
        return cls(success=True, status="SUCCEEDED", message=message)

    @classmethod
    def from_error(
        cls,
        error: IpError,
        *,
        error_code_override: str | None = None,
    ) -> ConnectionCheckResultDTO:
        return cls(
            success=False,
            status="FAILED",
            message=error.message,
            error_code=error_code_override or error.code.value,
            error=error,
        )


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
    catalog_version: int = 1
    catalog_hash: str = ""
    streams: Sequence[StreamSchemaDTO] = ()
    discovered_at: str = ""
    success: bool = True
    error_code: str | None = None
    error_message: str | None = None
    error: IpError | None = None

    @classmethod
    def from_error(cls, connection_id: str, error: IpError) -> DiscoveredCatalogDTO:
        return cls(
            connection_id=connection_id,
            success=False,
            error=error,
            error_code=error.code.value,
            error_message=error.message,
        )


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
    error_code: str | None = None
    error: IpError | None = None

    @classmethod
    def from_error(cls, error: IpError, record_id: str = "failed") -> WriteResultDTO:
        return cls(
            success=False,
            record_id=record_id,
            error=error,
            error_code=error.code.value,
            error_message=error.message,
        )


@dataclass(frozen=True)
class DropdownOptionDTO:
    """Option for dropdown configuration parameters."""

    label: str
    value: str


@dataclass(frozen=True)
class OAuthConfigDTO:
    """OAuth configuration for dynamic authorization modals."""

    auth_url: str
    token_url: str
    scopes: Sequence[str] = ()
    client_id: str | None = None


@dataclass(frozen=True)
class ConnectorPropertyDTO:
    """Specification of an individual configuration parameter for connection modals."""

    name: str
    label: str
    type: str
    required: bool = True
    default: str | int | float | bool | None = None
    description: str | None = None
    options: Sequence[DropdownOptionDTO] = ()
    oauth_config: OAuthConfigDTO | None = None


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
    properties: Sequence[ConnectorPropertyDTO] = ()
    description: str | None = None


@dataclass(frozen=True)
class AppSpecResultDTO:
    """Result of retrieving dynamic connector application specification."""

    success: bool
    spec: AppSpecDTO | None = None
    error_code: str | None = None
    error_message: str | None = None
    error: IpError | None = None

    @classmethod
    def ok(cls, spec: AppSpecDTO) -> AppSpecResultDTO:
        return cls(success=True, spec=spec)

    @classmethod
    def from_error(cls, error: IpError) -> AppSpecResultDTO:
        return cls(
            success=False,
            error=error,
            error_code=error.code.value,
            error_message=error.message,
        )
