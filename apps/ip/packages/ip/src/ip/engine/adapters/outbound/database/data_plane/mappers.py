"""Single-source-of-truth stateless ORM-to-Domain data mappers for Data Plane entities."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.models.data_plane import (
    GlobalEntityMapModel,
    InboundRecordModel,
    IpTraceEventModel,
    NormalizationRejectionModel,
    NormalizedRecordModel,
    OutboundRecordModel,
    ReplicaRecordModel,
    ReplicaRejectionModel,
)
from ip.engine.domain.enums import IngestionMode, OutboundDispatchStatus
from ip.engine.domain.models.global_entity_map import GlobalEntityMap
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.domain.models.normalized_record import NormalizedRecord
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.domain.models.replica_record import ReplicaRecord, ReplicaRejection
from ip.engine.domain.models.timeline_entry import IpTraceEvent
from ip.engine.domain.normalization import NormalizationRejectionEntry
from ip.engine.domain.services.outbound_error_classifier import redact_sensitive_headers


def inbound_record_to_domain(orm: InboundRecordModel) -> InboundRecord:
    """Maps an InboundRecordModel ORM row to an InboundRecord domain aggregate."""
    return InboundRecord(
        id=orm.id,
        tenant_id=orm.tenant_id,
        trace_id=orm.trace_id,
        correlation_id=orm.correlation_id,
        parent_trace_id=orm.parent_trace_id,
        original_trace_id=orm.original_trace_id,
        replay_count=orm.replay_count,
        connection_id=orm.connection_id,
        app_id=orm.app_id,
        stream_name=orm.stream_name,
        ingestion_mode=IngestionMode(orm.ingestion_mode),
        sync_run_id=orm.sync_run_id,
        generation_id=orm.generation_id,
        external_event_id=orm.external_event_id,
        request_headers=redact_sensitive_headers(orm.request_headers),
        request_body=dict(orm.request_body) if orm.request_body is not None else None,
        request_s3_key=orm.request_s3_key,
        request_size_bytes=orm.request_size_bytes,
        request_sha256=orm.request_sha256,
        response_status_code=orm.response_status_code,
        response_headers=(
            redact_sensitive_headers(orm.response_headers)
            if orm.response_headers is not None
            else None
        ),
        response_body=dict(orm.response_body) if orm.response_body is not None else None,
        response_s3_key=orm.response_s3_key,
        duration_ms=orm.duration_ms,
        received_at=orm.received_at,
    )


def replica_record_to_domain(orm: ReplicaRecordModel) -> ReplicaRecord:
    """Maps a ReplicaRecordModel ORM row to a ReplicaRecord domain aggregate."""
    return ReplicaRecord(
        id=orm.id,
        tenant_id=orm.tenant_id,
        trace_id=orm.trace_id,
        correlation_id=orm.correlation_id,
        connection_id=orm.connection_id,
        stream=orm.stream,
        record_key=orm.record_key,
        primary_key_values=tuple(orm.primary_key_values or ()),
        cursor_value=orm.cursor_value,
        cursor_kind=orm.cursor_kind,
        data=dict(orm.data),
        data_hash=orm.data_hash,
        version=orm.version,
        generation_id=orm.generation_id,
        last_seen_generation=orm.last_seen_generation,
        first_seen_at=orm.first_seen_at,
        extracted_at=orm.extracted_at,
        updated_at=orm.updated_at,
        deleted_at=orm.deleted_at,
        source_inbound_record_id=orm.source_inbound_record_id,
    )


def replica_rejection_to_domain(orm: ReplicaRejectionModel) -> ReplicaRejection:
    """Maps a ReplicaRejectionModel ORM row to a ReplicaRejection domain value object."""
    return ReplicaRejection(
        id=orm.id,
        tenant_id=orm.tenant_id,
        connection_id=orm.connection_id,
        stream=orm.stream,
        inbound_record_id=orm.inbound_record_id,
        record_index=orm.record_index,
        reason=orm.reason,
        detail=orm.detail,
        trace_id=orm.trace_id,
        created_at=orm.created_at,
    )


def normalized_record_to_domain(orm: NormalizedRecordModel) -> NormalizedRecord:
    """Maps a NormalizedRecordModel ORM row to a NormalizedRecord domain aggregate."""
    return NormalizedRecord(
        id=orm.id,
        tenant_id=orm.tenant_id,
        trace_id=orm.trace_id,
        correlation_id=orm.correlation_id,
        parent_trace_id=orm.parent_trace_id,
        original_trace_id=orm.original_trace_id,
        replay_count=orm.replay_count,
        connection_id=orm.connection_id,
        canonical_type=orm.canonical_type,
        source_id=orm.source_id,
        canonical_data=dict(orm.canonical_data),
        normalized_at=orm.normalized_at,
    )


def normalization_rejection_to_domain(
    orm: NormalizationRejectionModel,
) -> NormalizationRejectionEntry:
    """Maps a NormalizationRejectionModel ORM row to a NormalizationRejectionEntry domain value object."""
    return NormalizationRejectionEntry(
        id=orm.id,
        tenant_id=orm.tenant_id,
        replica_record_id=orm.replica_record_id,
        stream=orm.stream,
        transformation_id=orm.transformation_id,
        transformation_version=orm.transformation_version,
        reason_code=orm.reason_code,
        field_path=orm.field_path,
        detail=orm.detail,
        trace_id=orm.trace_id,
        correlation_id=orm.correlation_id,
        created_at=orm.created_at,
    )


def entity_map_to_domain(orm: GlobalEntityMapModel) -> GlobalEntityMap:
    """Maps a GlobalEntityMapModel ORM row to a GlobalEntityMap domain aggregate."""
    return GlobalEntityMap(
        id=orm.id,
        tenant_id=orm.tenant_id,
        trace_id=orm.trace_id,
        correlation_id=orm.correlation_id,
        parent_trace_id=orm.parent_trace_id,
        original_trace_id=orm.original_trace_id,
        replay_count=orm.replay_count,
        entity_domain=orm.entity_domain,
        canonical_id=orm.canonical_id,
        source_connection_id=orm.source_connection_id,
        source_entity_id=orm.source_entity_id,
        dest_connection_id=orm.dest_connection_id,
        dest_entity_id=orm.dest_entity_id,
        created_at=orm.created_at,
    )


def outbound_record_to_domain(orm: OutboundRecordModel) -> OutboundRecord:
    """Maps an OutboundRecordModel ORM row to an OutboundRecord domain aggregate."""
    return OutboundRecord(
        id=orm.id,
        tenant_id=orm.tenant_id,
        trace_id=orm.trace_id,
        correlation_id=orm.correlation_id,
        parent_trace_id=orm.parent_trace_id,
        original_trace_id=orm.original_trace_id,
        replay_count=orm.replay_count,
        connection_id=orm.connection_id,
        app_id=orm.app_id,
        stream_name=orm.stream_name,
        operation=orm.operation,
        idempotency_key=orm.idempotency_key,
        external_record_id=orm.external_record_id,
        target_url=orm.target_url,
        http_method=orm.http_method,
        request_headers=redact_sensitive_headers(orm.request_headers),
        request_body=dict(orm.request_body) if orm.request_body is not None else None,
        request_s3_key=orm.request_s3_key,
        request_size_bytes=orm.request_size_bytes,
        request_sha256=orm.request_sha256,
        status=OutboundDispatchStatus(orm.status),
        response_status_code=orm.response_status_code,
        response_headers=(
            redact_sensitive_headers(orm.response_headers)
            if orm.response_headers is not None
            else None
        ),
        response_body=dict(orm.response_body) if orm.response_body is not None else None,
        response_s3_key=orm.response_s3_key,
        duration_ms=orm.duration_ms,
        attempt_number=orm.attempt_number,
        failure_category=orm.failure_category,
        retry_after_seconds=orm.retry_after_seconds,
        error_message=orm.error_message,
        sent_at=orm.sent_at,
    )


def trace_event_to_domain(orm: IpTraceEventModel) -> IpTraceEvent:
    """Maps an IpTraceEventModel ORM row to an IpTraceEvent domain entity."""
    return IpTraceEvent(
        id=orm.id,
        tenant_id=orm.tenant_id,
        trace_id=orm.trace_id,
        correlation_id=orm.correlation_id,
        event_type=orm.event_type,
        actor=orm.actor,
        created_at=orm.created_at,
        metadata=dict(orm.metadata_) if orm.metadata_ is not None else None,
    )


__all__ = [
    "entity_map_to_domain",
    "inbound_record_to_domain",
    "normalization_rejection_to_domain",
    "normalized_record_to_domain",
    "outbound_record_to_domain",
    "replica_record_to_domain",
    "replica_rejection_to_domain",
    "trace_event_to_domain",
]
