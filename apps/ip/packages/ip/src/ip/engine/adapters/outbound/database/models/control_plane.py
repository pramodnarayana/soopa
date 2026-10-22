"""SQLAlchemy ORM models for the Integration Platform Control Plane (global_db, schema 'ip')."""

from __future__ import annotations

from datetime import datetime

from ip.engine.adapters.outbound.database.models.base import IpGlobalBase
from ip.engine.domain.types import JsonDict
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
        {"schema": "ip"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
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
        {"schema": "ip"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
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


class IpOutboxRecord(IpGlobalBase, OutboxMixin):
    """Control Plane transactional Outbox table in global_db (ip.outbox)."""

    __tablename__ = "outbox"
    ID_PREFIX = "ip_obx"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        default=lambda: generate_id(IpOutboxRecord.ID_PREFIX),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    __table_args__ = (
        Index(
            "ix_ip_outbox_pending",
            "status",
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
]
