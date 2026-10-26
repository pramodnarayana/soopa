"""Port contracts and DTOs for external application connectors.

All types are pure Python @dataclass(frozen=True) instances.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from seedwork.domain.types import JsonDict
from strace.domain import TraceEvent, TraceLineageItemDTO, TraceStatus

from ip.engine.domain.constants import DEFAULT_IDEMPOTENCY_HEADER
from ip.engine.domain.exceptions import IpError
from ip.engine.domain.models.global_entity_map import GlobalEntityMap
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.domain.models.normalized_record import NormalizedRecord
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.domain.models.replica_record import ReplicaRecord, ReplicaRejection
from ip.engine.domain.normalization import NormalizationRejectionEntry


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
    headers: dict[str, str] = field(default_factory=dict)
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
    request_headers: JsonDict = field(default_factory=dict)
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
        request_headers: JsonDict | None = None,
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


IpTraceLineageItemDTO = TraceLineageItemDTO


@dataclass(frozen=True, kw_only=True)
class IpTraceDTO:
    """End-to-end 5-layer waterfall snapshot of a single Integration Platform trace."""

    trace_id: str
    tenant_id: str
    correlation_id: str | None
    original_trace_id: str
    parent_trace_id: str | None
    replay_count: int
    status: TraceStatus
    inbound_record: InboundRecord | None = None
    replica_records: tuple[ReplicaRecord, ...] = ()
    replica_rejections: tuple[ReplicaRejection, ...] = ()
    normalized_records: tuple[NormalizedRecord, ...] = ()
    normalization_rejections: tuple[NormalizationRejectionEntry, ...] = ()
    entity_mappings: tuple[GlobalEntityMap, ...] = ()
    outbound_records: tuple[OutboundRecord, ...] = ()
    trace_events: tuple[TraceEvent, ...] = ()
