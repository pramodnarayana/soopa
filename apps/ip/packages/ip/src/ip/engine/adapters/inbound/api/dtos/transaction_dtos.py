"""HTTP Request and Response DTOs for the Integration Platform Transactions, Trace, and Replay API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from ip.engine.application.dtos.trace import (
    BulkReplayResultDTO,
    IpTraceDTO,
    IpTraceLineageItemDTO,
    ReplayTransactionResultDTO,
)
from ip.engine.domain.enums import ReplayStage
from ip.engine.domain.models.global_entity_map import GlobalEntityMap
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.domain.models.normalized_record import CanonicalDataDict, NormalizedRecord
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.domain.models.replica_record import ReplicaRecord, ReplicaRejection
from ip.engine.domain.normalization import NormalizationRejectionEntry
from pydantic import BaseModel, Field
from seedwork.domain.types import JsonDict, JsonPrimitive, JsonValue
from strace.domain import TraceEvent


def _format_dt(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _normalize_canonical_value(value: JsonValue | Decimal) -> JsonValue:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _normalize_canonical_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_canonical_value(item) for item in value]
    return value


def _normalize_canonical_data(canonical_data: CanonicalDataDict) -> JsonDict:
    return {str(k): _normalize_canonical_value(v) for k, v in canonical_data.items()}


class InboundRecordHttpResponse(BaseModel):
    """HTTP representation of an L1 InboundRecord stage snapshot."""

    id: str
    tenant_id: str
    trace_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    connection_id: str
    app_id: str
    stream_name: str
    ingestion_mode: str
    sync_run_id: str | None = None
    generation_id: int | None = None
    external_event_id: str | None = None
    request_headers: JsonDict = Field(default_factory=dict)
    request_body: JsonDict | None = None
    request_s3_key: str | None = None
    request_size_bytes: int
    request_sha256: str
    response_status_code: int | None = None
    response_headers: JsonDict | None = None
    response_body: JsonDict | None = None
    response_s3_key: str | None = None
    duration_ms: int | None = None
    received_at: str


class ReplicaRecordHttpResponse(BaseModel):
    """HTTP representation of an L2 ReplicaRecord stage snapshot."""

    id: str
    tenant_id: str
    trace_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    connection_id: str
    stream: str
    record_key: str
    primary_key_values: list[JsonPrimitive] = Field(default_factory=list)
    cursor_value: str | None = None
    cursor_kind: str | None = None
    data: JsonDict
    data_hash: str
    version: int
    generation_id: int
    last_seen_generation: int
    first_seen_at: str
    extracted_at: str
    updated_at: str
    deleted_at: str | None = None
    source_inbound_record_id: str


class ReplicaRejectionHttpResponse(BaseModel):
    """HTTP representation of an L2 ReplicaRejection entry."""

    id: str
    tenant_id: str
    connection_id: str
    stream: str
    inbound_record_id: str
    record_index: int
    reason: str
    detail: str
    trace_id: str
    created_at: str


class NormalizedRecordHttpResponse(BaseModel):
    """HTTP representation of an L3 NormalizedRecord stage snapshot."""

    id: str
    tenant_id: str
    trace_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    connection_id: str
    canonical_type: str
    source_id: str
    canonical_data: JsonDict
    normalized_at: str


class NormalizationRejectionHttpResponse(BaseModel):
    """HTTP representation of an L3 NormalizationRejectionEntry."""

    id: str
    tenant_id: str
    replica_record_id: str
    stream: str
    transformation_id: str
    transformation_version: int
    reason_code: str
    field_path: str | None = None
    detail: str
    trace_id: str
    correlation_id: str | None = None
    created_at: str


class GlobalEntityMapHttpResponse(BaseModel):
    """HTTP representation of an L3 GlobalEntityMap cross-reference entry."""

    id: str
    tenant_id: str
    trace_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    entity_domain: str
    canonical_id: str
    source_connection_id: str
    source_entity_id: str
    dest_connection_id: str | None = None
    dest_entity_id: str | None = None
    created_at: str


class OutboundRecordHttpResponse(BaseModel):
    """HTTP representation of an L5 OutboundRecord wire audit entry."""

    id: str
    tenant_id: str
    trace_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    connection_id: str
    app_id: str
    stream_name: str
    operation: str
    idempotency_key: str | None = None
    external_record_id: str | None = None
    target_url: str
    http_method: str
    request_headers: JsonDict = Field(default_factory=dict)
    request_body: JsonDict | None = None
    request_s3_key: str | None = None
    request_size_bytes: int
    request_sha256: str
    status: str
    response_status_code: int | None = None
    response_headers: JsonDict | None = None
    response_body: JsonDict | None = None
    response_s3_key: str | None = None
    duration_ms: int | None = None
    attempt_number: int
    failure_category: str | None = None
    retry_after_seconds: int | None = None
    error_message: str | None = None
    sent_at: str


class TraceEventHttpResponse(BaseModel):
    """HTTP representation of an immutable TraceEvent audit entry."""

    id: str
    tenant_id: str
    trace_id: str
    event_type: str
    actor: str
    correlation_id: str | None = None
    created_at: str
    metadata: JsonDict | None = None


class IpTraceHttpResponse(BaseModel):
    """Full 5-layer waterfall snapshot of an Integration Platform transaction trace."""

    trace_id: str
    tenant_id: str
    correlation_id: str | None = None
    original_trace_id: str
    parent_trace_id: str | None = None
    replay_count: int
    status: str
    inbound_record: InboundRecordHttpResponse | None = None
    replica_records: list[ReplicaRecordHttpResponse] = Field(default_factory=list)
    replica_rejections: list[ReplicaRejectionHttpResponse] = Field(default_factory=list)
    normalized_records: list[NormalizedRecordHttpResponse] = Field(default_factory=list)
    normalization_rejections: list[NormalizationRejectionHttpResponse] = Field(default_factory=list)
    entity_mappings: list[GlobalEntityMapHttpResponse] = Field(default_factory=list)
    outbound_records: list[OutboundRecordHttpResponse] = Field(default_factory=list)
    trace_events: list[TraceEventHttpResponse] = Field(default_factory=list)


class IpTraceLineageItemHttpResponse(BaseModel):
    """Lightweight summary of a single attempt in a trace's replay lineage tree."""

    trace_id: str
    correlation_id: str | None = None
    status: str
    primary_layer: str
    created_at: str | None = None
    replay_count: int = 0
    parent_trace_id: str | None = None
    original_trace_id: str | None = None


class ReplayTransactionHttpRequest(BaseModel):
    """Payload to replay an Integration Platform transaction from a specific stage."""

    stage: ReplayStage = Field(
        ...,
        description="Target pipeline stage to replay from (RETRY_INGEST, RETRY_NORMALIZE, RETRY_STITCH, RETRY_DELIVER)",
    )


class ModifyAndReplayHttpRequest(BaseModel):
    """Payload to override an L1 or L3 payload and trigger a new replay trace."""

    stage: ReplayStage = Field(
        ...,
        description="Target stage for payload modification (RETRY_INGEST or RETRY_STITCH)",
    )
    modified_payload: JsonDict = Field(
        ...,
        description="Replacement JSON object for the L1 request body or L3 canonical data",
    )


class ReplayTransactionHttpResponse(BaseModel):
    """Response returned when a single transaction replay or modify-and-replay is accepted."""

    status: str = "ACCEPTED"
    original_trace_id: str
    parent_trace_id: str
    new_trace_id: str
    stage: str
    replay_count: int
    correlation_id: str | None = None


class BulkReplayHttpRequest(BaseModel):
    """Payload to bulk-replay up to 100 transaction traces from a target stage."""

    trace_ids: list[str] = Field(..., min_length=1, max_length=100)
    stage: ReplayStage


class BulkReplayFailureItemHttpResponse(BaseModel):
    """Per-trace error item for a trace that could not be replayed during a bulk replay."""

    trace_id: str
    error_code: str
    message: str


class BulkReplayHttpResponse(BaseModel):
    """Response returned when a bulk transaction replay operation completes."""

    status: str = "ACCEPTED"
    stage: str
    replayed_count: int
    succeeded_trace_ids: list[str] = Field(default_factory=list)
    new_trace_ids: list[str] = Field(default_factory=list)
    failed_items: list[BulkReplayFailureItemHttpResponse] = Field(default_factory=list)


def map_inbound_record_to_http(record: InboundRecord) -> InboundRecordHttpResponse:
    return InboundRecordHttpResponse(
        id=record.id,
        tenant_id=record.tenant_id,
        trace_id=record.trace_id,
        correlation_id=record.correlation_id,
        parent_trace_id=record.parent_trace_id,
        original_trace_id=record.original_trace_id,
        replay_count=record.replay_count,
        connection_id=record.connection_id,
        app_id=record.app_id,
        stream_name=record.stream_name,
        ingestion_mode=record.ingestion_mode.value,
        sync_run_id=record.sync_run_id,
        generation_id=record.generation_id,
        external_event_id=record.external_event_id,
        request_headers=dict(record.request_headers),
        request_body=dict(record.request_body) if record.request_body is not None else None,
        request_s3_key=record.request_s3_key,
        request_size_bytes=record.request_size_bytes,
        request_sha256=record.request_sha256,
        response_status_code=record.response_status_code,
        response_headers=(
            dict(record.response_headers) if record.response_headers is not None else None
        ),
        response_body=dict(record.response_body) if record.response_body is not None else None,
        response_s3_key=record.response_s3_key,
        duration_ms=record.duration_ms,
        received_at=record.received_at.isoformat(),
    )


def map_replica_record_to_http(record: ReplicaRecord) -> ReplicaRecordHttpResponse:
    return ReplicaRecordHttpResponse(
        id=record.id,
        tenant_id=record.tenant_id,
        trace_id=record.trace_id,
        correlation_id=record.correlation_id,
        parent_trace_id=record.parent_trace_id,
        original_trace_id=record.original_trace_id,
        replay_count=record.replay_count,
        connection_id=record.connection_id,
        stream=record.stream,
        record_key=record.record_key,
        primary_key_values=list(record.primary_key_values),
        cursor_value=record.cursor_value,
        cursor_kind=record.cursor_kind,
        data=dict(record.data),
        data_hash=record.data_hash,
        version=record.version,
        generation_id=record.generation_id,
        last_seen_generation=record.last_seen_generation,
        first_seen_at=record.first_seen_at.isoformat(),
        extracted_at=record.extracted_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
        deleted_at=_format_dt(record.deleted_at),
        source_inbound_record_id=record.source_inbound_record_id,
    )


def map_replica_rejection_to_http(rejection: ReplicaRejection) -> ReplicaRejectionHttpResponse:
    return ReplicaRejectionHttpResponse(
        id=rejection.id,
        tenant_id=rejection.tenant_id,
        connection_id=rejection.connection_id,
        stream=rejection.stream,
        inbound_record_id=rejection.inbound_record_id,
        record_index=rejection.record_index,
        reason=rejection.reason,
        detail=rejection.detail,
        trace_id=rejection.trace_id,
        created_at=rejection.created_at.isoformat(),
    )


def map_normalized_record_to_http(record: NormalizedRecord) -> NormalizedRecordHttpResponse:
    return NormalizedRecordHttpResponse(
        id=record.id,
        tenant_id=record.tenant_id,
        trace_id=record.trace_id,
        correlation_id=record.correlation_id,
        parent_trace_id=record.parent_trace_id,
        original_trace_id=record.original_trace_id,
        replay_count=record.replay_count,
        connection_id=record.connection_id,
        canonical_type=record.canonical_type,
        source_id=record.source_id,
        canonical_data=_normalize_canonical_data(record.canonical_data),
        normalized_at=record.normalized_at.isoformat(),
    )


def map_normalization_rejection_to_http(
    rejection: NormalizationRejectionEntry,
) -> NormalizationRejectionHttpResponse:
    return NormalizationRejectionHttpResponse(
        id=rejection.id,
        tenant_id=rejection.tenant_id,
        replica_record_id=rejection.replica_record_id,
        stream=rejection.stream,
        transformation_id=rejection.transformation_id,
        transformation_version=rejection.transformation_version,
        reason_code=rejection.reason_code,
        field_path=rejection.field_path,
        detail=rejection.detail,
        trace_id=rejection.trace_id,
        correlation_id=rejection.correlation_id,
        created_at=rejection.created_at.isoformat(),
    )


def map_entity_mapping_to_http(mapping: GlobalEntityMap) -> GlobalEntityMapHttpResponse:
    return GlobalEntityMapHttpResponse(
        id=mapping.id,
        tenant_id=mapping.tenant_id,
        trace_id=mapping.trace_id,
        correlation_id=mapping.correlation_id,
        parent_trace_id=mapping.parent_trace_id,
        original_trace_id=mapping.original_trace_id,
        replay_count=mapping.replay_count,
        entity_domain=mapping.entity_domain,
        canonical_id=mapping.canonical_id,
        source_connection_id=mapping.source_connection_id,
        source_entity_id=mapping.source_entity_id,
        dest_connection_id=mapping.dest_connection_id,
        dest_entity_id=mapping.dest_entity_id,
        created_at=mapping.created_at.isoformat(),
    )


def map_outbound_record_to_http(record: OutboundRecord) -> OutboundRecordHttpResponse:
    return OutboundRecordHttpResponse(
        id=record.id,
        tenant_id=record.tenant_id,
        trace_id=record.trace_id,
        correlation_id=record.correlation_id,
        parent_trace_id=record.parent_trace_id,
        original_trace_id=record.original_trace_id,
        replay_count=record.replay_count,
        connection_id=record.connection_id,
        app_id=record.app_id,
        stream_name=record.stream_name,
        operation=record.operation,
        idempotency_key=record.idempotency_key,
        external_record_id=record.external_record_id,
        target_url=record.target_url,
        http_method=record.http_method,
        request_headers=dict(record.request_headers),
        request_body=dict(record.request_body) if record.request_body is not None else None,
        request_s3_key=record.request_s3_key,
        request_size_bytes=record.request_size_bytes,
        request_sha256=record.request_sha256,
        status=record.status.value,
        response_status_code=record.response_status_code,
        response_headers=(
            dict(record.response_headers) if record.response_headers is not None else None
        ),
        response_body=dict(record.response_body) if record.response_body is not None else None,
        response_s3_key=record.response_s3_key,
        duration_ms=record.duration_ms,
        attempt_number=record.attempt_number,
        failure_category=record.failure_category,
        retry_after_seconds=record.retry_after_seconds,
        error_message=record.error_message,
        sent_at=record.sent_at.isoformat(),
    )


def map_trace_event_to_http(event: TraceEvent) -> TraceEventHttpResponse:
    return TraceEventHttpResponse(
        id=event.id,
        tenant_id=event.tenant_id,
        trace_id=event.trace_id,
        event_type=event.event_type,
        actor=event.actor,
        correlation_id=event.correlation_id,
        created_at=event.created_at.isoformat(),
        metadata=dict(event.metadata) if event.metadata is not None else None,
    )


def map_ip_trace_dto_to_http(dto: IpTraceDTO) -> IpTraceHttpResponse:
    return IpTraceHttpResponse(
        trace_id=dto.trace_id,
        tenant_id=dto.tenant_id,
        correlation_id=dto.correlation_id,
        original_trace_id=dto.original_trace_id,
        parent_trace_id=dto.parent_trace_id,
        replay_count=dto.replay_count,
        status=dto.status.value if hasattr(dto.status, "value") else str(dto.status),
        inbound_record=(
            map_inbound_record_to_http(dto.inbound_record)
            if dto.inbound_record is not None
            else None
        ),
        replica_records=[map_replica_record_to_http(r) for r in dto.replica_records],
        replica_rejections=[map_replica_rejection_to_http(r) for r in dto.replica_rejections],
        normalized_records=[map_normalized_record_to_http(r) for r in dto.normalized_records],
        normalization_rejections=[
            map_normalization_rejection_to_http(r) for r in dto.normalization_rejections
        ],
        entity_mappings=[map_entity_mapping_to_http(m) for m in dto.entity_mappings],
        outbound_records=[map_outbound_record_to_http(r) for r in dto.outbound_records],
        trace_events=[map_trace_event_to_http(e) for e in dto.trace_events],
    )


def map_lineage_item_to_http(item: IpTraceLineageItemDTO) -> IpTraceLineageItemHttpResponse:
    return IpTraceLineageItemHttpResponse(
        trace_id=item.trace_id,
        correlation_id=item.correlation_id,
        status=item.status.value if hasattr(item.status, "value") else str(item.status),
        primary_layer=item.primary_layer,
        created_at=_format_dt(item.created_at),
        replay_count=item.replay_count,
        parent_trace_id=item.parent_trace_id,
        original_trace_id=item.original_trace_id,
    )


def map_replay_result_to_http(dto: ReplayTransactionResultDTO) -> ReplayTransactionHttpResponse:
    return ReplayTransactionHttpResponse(
        status="ACCEPTED",
        original_trace_id=dto.original_trace_id,
        parent_trace_id=dto.parent_trace_id,
        new_trace_id=dto.new_trace_id,
        stage=dto.stage.value,
        replay_count=dto.replay_count,
        correlation_id=dto.correlation_id,
    )


def map_bulk_replay_result_to_http(dto: BulkReplayResultDTO) -> BulkReplayHttpResponse:
    return BulkReplayHttpResponse(
        status="ACCEPTED",
        stage=dto.stage.value,
        replayed_count=dto.replayed_count,
        succeeded_trace_ids=list(dto.succeeded_trace_ids),
        new_trace_ids=list(dto.new_trace_ids),
        failed_items=[
            BulkReplayFailureItemHttpResponse(
                trace_id=item.trace_id,
                error_code=item.error_code.value,
                message=item.message,
            )
            for item in dto.failed_items
        ],
    )


__all__ = [
    "BulkReplayFailureItemHttpResponse",
    "BulkReplayHttpRequest",
    "BulkReplayHttpResponse",
    "GlobalEntityMapHttpResponse",
    "InboundRecordHttpResponse",
    "IpTraceHttpResponse",
    "IpTraceLineageItemHttpResponse",
    "ModifyAndReplayHttpRequest",
    "NormalizationRejectionHttpResponse",
    "NormalizedRecordHttpResponse",
    "OutboundRecordHttpResponse",
    "ReplayTransactionHttpRequest",
    "ReplayTransactionHttpResponse",
    "ReplicaRecordHttpResponse",
    "ReplicaRejectionHttpResponse",
    "TraceEventHttpResponse",
    "map_bulk_replay_result_to_http",
    "map_ip_trace_dto_to_http",
    "map_lineage_item_to_http",
    "map_replay_result_to_http",
]
