"""Segregated port protocols (ISP) and wire contracts for Integration Platform connectors."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from seedwork.domain.types import JsonDict, JsonValue

from ip.engine.domain.constants import DEFAULT_IDEMPOTENCY_HEADER
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
    cursor_value: str | None = None


@dataclass(frozen=True)
class WriteRecordCommand:
    """Command to mutate a record in a target external application."""

    stream_name: str
    operation: str  # 'CREATE' | 'UPDATE' | 'UPSERT' | 'DELETE'
    payload: JsonDict
    record_id: str | None = None
    idempotency_key: str | None = None
    idempotency_header_name: str = DEFAULT_IDEMPOTENCY_HEADER
    headers: Mapping[str, str] = field(default_factory=dict)
    correlation_id: str | None = None


@dataclass(frozen=True)
class WriteResultDTO:
    """Outcome of writing a record to a target external application with wire telemetry."""

    success: bool
    record_id: str
    destination_id: str | None = None
    error_message: str | None = None
    error_code: str | None = None
    error: IpError | None = None
    target_url: str = ""
    http_method: str = "POST"
    request_headers: Mapping[str, JsonValue] = field(default_factory=dict)
    response_status_code: int | None = None
    response_headers: JsonDict | None = None
    response_body: JsonDict | None = None
    raw_response_bytes: bytes | None = None
    duration_ms: int | None = None
    retry_after_seconds: int | None = None
    failure_category: str | None = None

    @classmethod
    def from_error(
        cls,
        error: IpError,
        record_id: str = "failed",
        *,
        target_url: str = "",
        http_method: str = "POST",
        request_headers: Mapping[str, JsonValue] | None = None,
        response_status_code: int | None = None,
        response_headers: JsonDict | None = None,
        response_body: JsonDict | None = None,
        raw_response_bytes: bytes | None = None,
        duration_ms: int | None = None,
        retry_after_seconds: int | None = None,
        failure_category: str | None = None,
    ) -> WriteResultDTO:
        return cls(
            success=False,
            record_id=record_id,
            error=error,
            error_code=error.code.value,
            error_message=error.message,
            target_url=target_url,
            http_method=http_method,
            request_headers=dict(request_headers or {}),
            response_status_code=response_status_code,
            response_headers=response_headers,
            response_body=response_body,
            raw_response_bytes=raw_response_bytes,
            duration_ms=duration_ms,
            retry_after_seconds=retry_after_seconds,
            failure_category=failure_category,
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
class AppSpecDTO:
    """Specification schema for dynamic UI configuration form generation."""

    app_id: str
    display_name: str
    auth_type: str
    category: str
    properties: Sequence[ConnectorPropertyDTO] = ()
    description: str | None = None


class ConnectorMetadataPort(Protocol):
    """Port for connector specification, health check, and schema discovery."""

    @property
    @abstractmethod
    def app_id(self) -> str:
        """Unique identifier of the external application (e.g. 'http', 'sftp')."""
        ...

    @abstractmethod
    def spec(self) -> AppSpecDTO:
        """Returns dynamic property schema and configuration parameters needed by the connector."""
        ...

    @abstractmethod
    async def check(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> ConnectionCheckResultDTO:
        """Validates connectivity and credentials with the external system."""
        ...

    @abstractmethod
    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> DiscoveredCatalogDTO:
        """Introspects the external system to discover available objects and schemas."""
        ...


class SourceConnectorPort(ConnectorMetadataPort, Protocol):
    """Hexagonal outbound port for source (ingress/read) connectors."""

    @property
    def last_error(self) -> IpError | None:
        """Returns the last domain/operational error encountered during stream reading, if any."""
        return None

    @abstractmethod
    async def list_objects(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Sequence[str]:
        """Lists discrete object identifiers from a stream for browsing or AI agent inspection."""
        ...

    @abstractmethod
    def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        """Streams records asynchronously from the external system."""
        ...

    @abstractmethod
    async def fetch_record(
        self,
        stream_name: str,
        record_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> RecordEnvelopeDTO | None:
        """Fetches a single record by primary key (Fetch-on-Notify / Thin Push)."""
        ...


class DestinationConnectorPort(ConnectorMetadataPort, Protocol):
    """Hexagonal outbound port for destination (egress/write) connectors."""

    @abstractmethod
    async def write_record(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> WriteResultDTO:
        """Writes/mutates a record in the external application."""
        ...


class ConnectorPort(SourceConnectorPort, DestinationConnectorPort, Protocol):
    """Full bidirectional connector port combining SourceConnectorPort and DestinationConnectorPort."""

    ...


__all__ = [
    "AppSpecDTO",
    "ConnectionCheckResultDTO",
    "ConnectorMetadataPort",
    "ConnectorPort",
    "ConnectorPropertyDTO",
    "DestinationConnectorPort",
    "DiscoveredCatalogDTO",
    "DropdownOptionDTO",
    "OAuthConfigDTO",
    "RecordEnvelopeDTO",
    "SourceConnectorPort",
    "StreamFieldDTO",
    "StreamSchemaDTO",
    "WriteRecordCommand",
    "WriteResultDTO",
]
