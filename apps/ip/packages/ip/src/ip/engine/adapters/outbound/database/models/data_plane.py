"""SQLAlchemy ORM models for the Integration Platform Data Plane (tenant shards, public schema)."""

from __future__ import annotations

from datetime import datetime

from ip.engine.adapters.outbound.database.models.base import IpTenantBase
from ip.engine.domain.types import JsonDict
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

from database.models.common import OutboxMixin


class InboundRecordModel(IpTenantBase):
    """Database record representation of the inbound_records audit table in tenant shards."""

    __tablename__ = "inbound_records"
    __table_args__ = (
        PrimaryKeyConstraint("id", "received_at"),
        Index("idx_inbound_trace", "tenant_id", "trace_id"),
        Index("idx_inbound_corr", "tenant_id", "correlation_id"),
        Index("idx_inbound_conn", "tenant_id", "connection_id"),
        Index("idx_inbound_app", "tenant_id", "app_id"),
    )

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stream_name: Mapped[str] = mapped_column(String(128), nullable=False)
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
            "entity_type",
            "entity_id",
            name="uq_ip_replica_record_identity",
        ),
        Index("idx_replica_tenant_entity", "tenant_id", "entity_type"),
        Index("idx_replica_data_hash", "tenant_id", "data_hash"),
        Index("idx_replica_trace", "tenant_id", "trace_id"),
        Index("idx_replica_corr", "tenant_id", "correlation_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    data: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, default=dict)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NormalizedRecordModel(IpTenantBase):
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
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    normalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GlobalEntityMapModel(IpTenantBase):
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
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entity_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    dest_connection_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dest_entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboundRecordModel(IpTenantBase):
    """Database record representation of the outbound_records audit table in tenant shards."""

    __tablename__ = "outbound_records"
    __table_args__ = (
        PrimaryKeyConstraint("id", "sent_at"),
        Index("idx_outbound_trace", "tenant_id", "trace_id"),
        Index("idx_outbound_corr", "tenant_id", "correlation_id"),
        Index("idx_outbound_conn", "tenant_id", "connection_id"),
        Index("idx_outbound_app", "tenant_id", "app_id"),
        Index("idx_outbound_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stream_name: Mapped[str] = mapped_column(String(128), nullable=False)
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
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IpTraceEventModel(IpTenantBase):
    """Database record representation of the ip_trace_events ledger (seedwork.models.TraceEvent)."""

    __tablename__ = "ip_trace_events"
    __table_args__ = (
        PrimaryKeyConstraint("id", "created_at"),
        Index("idx_ip_trace_events_trace", "tenant_id", "trace_id", "created_at"),
        Index("idx_ip_trace_events_corr", "tenant_id", "correlation_id"),
        Index("idx_ip_trace_events_type", "tenant_id", "event_type", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="SYSTEM")
    metadata_: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


TimelineEntryModel = IpTraceEventModel


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
    "NormalizedRecordModel",
    "OutboundRecordModel",
    "ReplicaRecordModel",
    "TimelineEntryModel",
]
