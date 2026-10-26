"""SQLAlchemy ORM models for the Integration Platform Data Plane (tenant shards, public schema)."""

from __future__ import annotations

from datetime import datetime

from ip.engine.adapters.outbound.database.models.base import IpTenantBase
from seedwork.domain.types import JsonDict, JsonPrimitive
from seedwork.utils import generate_id
from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from strace.adapters import TenantTraceableOrmModel, TraceEventMixin

from database.models.common import OutboxMixin


class InboundRecordModel(IpTenantBase, TenantTraceableOrmModel):
    """Database record representation of the inbound_records audit table in tenant shards."""

    __tablename__ = "inbound_records"
    __table_args__ = (
        PrimaryKeyConstraint("id", "received_at"),
        Index("idx_inbound_trace", "tenant_id", "trace_id"),
        Index("idx_inbound_corr", "tenant_id", "correlation_id"),
        Index("idx_inbound_conn", "tenant_id", "connection_id"),
        Index("idx_inbound_app", "tenant_id", "app_id"),
        Index(
            "uq_inbound_external_event",
            "tenant_id",
            "connection_id",
            "external_event_id",
            unique=True,
            postgresql_where=text("external_event_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    stream_name: Mapped[str] = mapped_column(String(128), nullable=False)
    ingestion_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="PUSH_FULL"
    )
    sync_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_headers: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, default=dict)
    request_body: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    request_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    request_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_headers: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    response_body: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    response_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReplicaRecordModel(IpTenantBase):
    """Database record representation of the replica_records table in tenant shards."""

    __tablename__ = "replica_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "connection_id",
            "stream",
            "record_key",
            name="uq_ip_replica_record_identity",
        ),
        Index("idx_replica_tenant_stream", "tenant_id", "stream"),
        Index("idx_replica_data_hash", "tenant_id", "data_hash"),
        Index("idx_replica_trace", "tenant_id", "trace_id"),
        Index("idx_replica_corr", "tenant_id", "correlation_id"),
        Index("idx_replica_gen", "tenant_id", "connection_id", "stream", "last_seen_generation"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    stream: Mapped[str] = mapped_column(String(128), nullable=False)
    record_key: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_key_values: Mapped[list[JsonPrimitive]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    cursor_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cursor_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    data: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, default=dict)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    generation_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    last_seen_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_inbound_record_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ReplicaRejectionModel(IpTenantBase):
    """Database record representation of rejected records at Layer 2."""

    __tablename__ = "replica_rejections"
    __table_args__ = (
        Index("idx_rejection_tenant_conn", "tenant_id", "connection_id", "stream"),
        Index("idx_rejection_trace", "tenant_id", "trace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    stream: Mapped[str] = mapped_column(String(128), nullable=False)
    inbound_record_id: Mapped[str] = mapped_column(String(64), nullable=False)
    record_index: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NormalizedRecordModel(IpTenantBase, TenantTraceableOrmModel):
    """Database record representation of the normalized_records table (Layer 3 Universal Canonical Index)."""

    __tablename__ = "normalized_records"
    __table_args__ = (
        Index("idx_norm_tenant_type", "tenant_id", "canonical_type"),
        Index("idx_norm_source_id", "tenant_id", "canonical_type", "source_id"),
        Index("idx_norm_trace", "tenant_id", "trace_id"),
        Index("idx_norm_corr", "tenant_id", "correlation_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_data: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, default=dict)
    normalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GlobalEntityMapModel(IpTenantBase, TenantTraceableOrmModel):
    """Database record representation of the global_entity_map table (Cross-System ID Crosswalk)."""

    __tablename__ = "global_entity_map"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "entity_domain",
            "source_connection_id",
            "source_entity_id",
            name="uq_ip_entity_map_source",
        ),
        Index("idx_entity_map_canonical", "tenant_id", "canonical_id"),
        Index("idx_entity_map_trace", "tenant_id", "trace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    dest_connection_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dest_entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboundRecordModel(IpTenantBase, TenantTraceableOrmModel):
    """Database record representation of the outbound_records audit table in tenant shards."""

    __tablename__ = "outbound_records"
    __table_args__ = (
        PrimaryKeyConstraint("id", "sent_at"),
        Index("idx_outbound_trace", "tenant_id", "trace_id"),
        Index("idx_outbound_corr", "tenant_id", "correlation_id"),
        Index("idx_outbound_conn", "tenant_id", "connection_id"),
        Index("idx_outbound_app", "tenant_id", "app_id"),
        Index("idx_outbound_status", "tenant_id", "status"),
        Index("idx_outbound_idempotency", "tenant_id", "connection_id", "idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    stream_name: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATE")
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    http_method: Mapped[str] = mapped_column(String(16), nullable=False)
    request_headers: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, default=dict)
    request_body: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    request_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    request_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_headers: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    response_body: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    response_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IpTraceEventModel(IpTenantBase, TraceEventMixin):
    """Database record representation of the ip_trace_events ledger (trace.domain.TraceEvent)."""

    __tablename__ = "ip_trace_events"
    __table_args__ = (
        PrimaryKeyConstraint("id", "created_at"),
        Index("idx_ip_trace_events_trace", "tenant_id", "trace_id", "created_at"),
        Index("idx_ip_trace_events_corr", "tenant_id", "correlation_id"),
        Index("idx_ip_trace_events_type", "tenant_id", "event_type", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)


TimelineEntryModel = IpTraceEventModel


class NormalizationLedgerModel(IpTenantBase):
    """Database record representation of the normalization_ledger table on tenant shards."""

    __tablename__ = "normalization_ledger"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "replica_record_id",
            "mapping_id",
            "mapping_version",
            name="uq_ip_norm_ledger_replica_mapping",
        ),
        Index("idx_norm_ledger_replica", "tenant_id", "replica_record_id"),
        Index("idx_norm_ledger_trace", "tenant_id", "trace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    replica_record_id: Mapped[str] = mapped_column(String(64), nullable=False)
    replica_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mapping_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False)
    produced_canonical_refs: Mapped[list[list[str]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NormalizationRejectionModel(IpTenantBase):
    """Database record representation of the normalization_rejections table on tenant shards."""

    __tablename__ = "normalization_rejections"
    __table_args__ = (
        Index("idx_norm_rej_tenant_replica", "tenant_id", "replica_record_id"),
        Index("idx_norm_rej_trace", "tenant_id", "trace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    replica_record_id: Mapped[str] = mapped_column(String(64), nullable=False)
    stream: Mapped[str] = mapped_column(String(128), nullable=False)
    mapping_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    field_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NormalizationShadowDiffModel(IpTenantBase):
    """Database record representation of candidate mapper differences in shadow mode."""

    __tablename__ = "normalization_shadow_diffs"
    __table_args__ = (
        Index("idx_norm_diff_replica", "tenant_id", "replica_record_id"),
        Index("idx_norm_diff_trace", "tenant_id", "trace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    replica_record_id: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    diff_data: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, default=dict)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PendingReferenceModel(IpTenantBase):
    """Database record representation of unresolved late-arriving references."""

    __tablename__ = "pending_references"
    __table_args__ = (
        Index(
            "idx_pending_ref_target",
            "tenant_id",
            "source_connection_id",
            "target_canonical_type",
            "target_source_id",
        ),
        Index("idx_pending_ref_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_canonical_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    referencing_canonical_type: Mapped[str] = mapped_column(String(64), nullable=False)
    referencing_source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    referencing_field: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IpDataPlaneOutboxRecord(IpTenantBase, OutboxMixin):
    """Data Plane transactional Outbox table in tenant shards (public.ip_outbox)."""

    __tablename__ = "ip_outbox"
    ID_PREFIX = "ip_dp_obx"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: generate_id(IpDataPlaneOutboxRecord.ID_PREFIX),
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    __table_args__ = (
        Index(
            "ix_ip_dp_outbox_pending",
            "status",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
    )


__all__ = [
    "GlobalEntityMapModel",
    "InboundRecordModel",
    "IpDataPlaneOutboxRecord",
    "IpTraceEventModel",
    "NormalizationLedgerModel",
    "NormalizationRejectionModel",
    "NormalizationShadowDiffModel",
    "NormalizedRecordModel",
    "OutboundRecordModel",
    "PendingReferenceModel",
    "ReplicaRecordModel",
    "ReplicaRejectionModel",
    "TimelineEntryModel",
]
