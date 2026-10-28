"""SQLAlchemy ORM models for the Integration Platform Control Plane (global_db, schema 'ip')."""

from __future__ import annotations

from datetime import datetime

from ip.engine.adapters.outbound.database.models.base import IpGlobalBase
from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.common import OutboxMixin


class ConnectionRecord(IpGlobalBase):
    """Database record representation of the ip.connections table."""

    __tablename__ = "connections"
    __table_args__ = (
        Index(
            "uq_tenant_active_fingerprint",
            "tenant_id",
            "connection_fingerprint",
            unique=True,
            postgresql_where=text("status != 'DEACTIVATED'"),
        ),
        Index("ix_ip_connections_tenant_id", "tenant_id"),
        {"schema": "ip"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(32), nullable=False)
    public_config: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, default=dict)
    encrypted_credentials: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    key_encryption_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    connection_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING_AUTH")
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConnectionCatalogRecord(IpGlobalBase):
    """Database record representation of the ip.connection_catalogs table."""

    __tablename__ = "connection_catalogs"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "catalog_version", name="uq_ip_catalog_connection_version"
        ),
        Index("ix_ip_connection_catalogs_connection_id", "connection_id"),
        {"schema": "ip"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    catalog_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    catalog_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_definition: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConnectionStreamStateRecord(IpGlobalBase):
    """Database record representation of the ip.connection_stream_states table."""

    __tablename__ = "connection_stream_states"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "connection_id",
            "stream_name",
            name="uq_ip_stream_state_tenant_conn_stream",
        ),
        Index("idx_ip_stream_state_conn", "tenant_id", "connection_id"),
        {"schema": "ip"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    connection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ip.connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    stream_name: Mapped[str] = mapped_column(String(128), nullable=False)
    cursor_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cursor_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    records_synced_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SyncRunRecord(IpGlobalBase):
    """Database representation of the ip.sync_runs table for pull sync tracking."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        Index(
            "uq_ip_sync_runs_active_stream",
            "connection_id",
            "stream",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'RUNNING')"),
        ),
        Index("idx_ip_sync_runs_tenant_conn", "tenant_id", "connection_id"),
        Index("idx_ip_sync_runs_status", "status", "created_at"),
        {"schema": "ip"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    connection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ip.connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    stream: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    generation_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    start_checkpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
    end_checkpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
    pages_count: Mapped[int] = mapped_column("pages_synced", Integer, nullable=False, default=0)
    records_count: Mapped[int] = mapped_column(
        "records_synced", BigInteger, nullable=False, default=0
    )
    bytes_count: Mapped[int] = mapped_column("bytes_synced", BigInteger, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column("retries_count", Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TransformationRecord(IpGlobalBase):
    """Database record representation of the ip.transformations table."""

    __tablename__ = "transformations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "connection_id", "stream", name="uq_ip_transformation_stream"
        ),
        Index("ix_ip_transformations_conn", "connection_id"),
        {"schema": "ip"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    stream: Mapped[str] = mapped_column(String(128), nullable=False)
    transformation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    transformation_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    shadow_transformation_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StitchRecord(IpGlobalBase):
    """Database record representation of the ip.stitches table."""

    __tablename__ = "stitches"
    __table_args__ = (
        Index(
            "ix_ip_stitches_tenant_event",
            "tenant_id",
            "canonical_event_type",
        ),
        Index("ix_ip_stitches_workflow", "workflow_id", "workflow_version"),
        {"schema": "ip"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    canonical_event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    is_trigger: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    condition_event_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key_field: Mapped[str] = mapped_column(String(128), nullable=False, default="id")
    concurrency_key_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_hint_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IpOutboxRecord(IpGlobalBase, OutboxMixin):
    """Control Plane transactional Outbox table in global_db (ip.outbox)."""

    __tablename__ = "outbox"
    ID_PREFIX = "ip_obx"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: generate_id(IpOutboxRecord.ID_PREFIX),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("ix_ip_outbox_tenant_id", "tenant_id"),
        Index(
            "ix_ip_outbox_pending",
            "status",
            "lane",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        {"schema": "ip"},
    )


__all__ = [
    "ConnectionCatalogRecord",
    "ConnectionRecord",
    "ConnectionStreamStateRecord",
    "IpOutboxRecord",
    "StitchRecord",
    "SyncRunRecord",
    "TransformationRecord",
]
