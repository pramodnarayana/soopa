from datetime import datetime
from typing import Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func, text

from .common import OutboxMixin


class GlobalBase(DeclarativeBase):
    pass


class DatabaseShard(GlobalBase):
    __tablename__ = "database_shards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    dsn: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Tenant(GlobalBase):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idp_tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    shard_id: Mapped[int] = mapped_column(Integer, ForeignKey("database_shards.id"), nullable=False)
    tier: Mapped[str] = mapped_column(String(50), nullable=False, default="standard")
    allow_private_as2: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    shard_schema: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(GlobalBase):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idp_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("uq_users_email_lower", text("lower(email)"), unique=True),)


class TenantUser(GlobalBase):
    __tablename__ = "tenant_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")

    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user"),)


class AS2Partner(GlobalBase):
    """
    Global AS2 Partners (both our local gateway config, and remote shared configs).
    """

    __tablename__ = "as2_partners"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )  # Null if shared global
    is_local: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    as2_id: Mapped[str] = mapped_column(String(255), nullable=False)
    public_cert_pem: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Retained for legacy/external, but vault preferred
    public_cert_vault_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    private_key_vault_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    prev_public_cert_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    prev_public_cert_vault_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prev_private_key_vault_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "as2_id", name="uq_tenant_as2_id"),
        Index(
            "uq_global_as2_id", "as2_id", unique=True, postgresql_where=text("tenant_id IS NULL")
        ),
    )


class AS2Partnership(GlobalBase):
    """
    OpenAS2 style Partnership (links Local Partner to Remote Partner)
    and stores all MDN and Encryption properties.
    """

    __tablename__ = "as2_partnerships"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    local_partner_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id", ondelete="CASCADE"), nullable=False
    )
    remote_partner_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id", ondelete="CASCADE"), nullable=False
    )

    # Core AS2 Networking
    credentials_vault_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Core AS2 Protocol Settings
    mdn_type: Mapped[str] = mapped_column(String(50), nullable=False, default="SYNC")
    mdn_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    encryption_algorithm: Mapped[str] = mapped_column(String(50), nullable=False, default="AES256")
    signature_algorithm: Mapped[str] = mapped_column(String(50), nullable=False, default="SHA256")
    edi_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Advanced OpenAS2 settings
    advanced_flags: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("local_partner_id", "remote_partner_id", name="uq_as2_partnership"),
    )


class Outbox(GlobalBase, OutboxMixin):
    __tablename__ = "outbox"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_global_outbox_pending",
            "status",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
    )


class SystemAuditLog(GlobalBase):
    __tablename__ = "system_audit_log"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    trace_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_system_audit_log_tenant_time", "tenant_id", "created_at"),)
