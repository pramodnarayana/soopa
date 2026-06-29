from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func, text

from .common import OutboxMixin


class GlobalBase(DeclarativeBase):
    __allow_unmapped__ = True


class DatabaseShard(GlobalBase):
    __tablename__ = "database_shards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    dsn = Column(String(1024), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Tenant(GlobalBase):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    idp_tenant_id = Column(String(255), nullable=True, unique=True)
    name = Column(String(255), nullable=False, unique=True)
    shard_id = Column(Integer, ForeignKey("database_shards.id"), nullable=False)
    tier = Column(String(50), nullable=False, default="standard")
    allow_private_as2 = Column(Boolean, nullable=False, server_default="false")
    shard_schema = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class User(GlobalBase):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    idp_user_id = Column(String(255), nullable=True, unique=True)
    email = Column(String(255), nullable=False)
    name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("uq_users_email_lower", text("lower(email)"), unique=True),)


class TenantUser(GlobalBase):
    __tablename__ = "tenant_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(50), nullable=False, default="member")

    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user"),)


class AS2Partner(GlobalBase):
    """
    Global AS2 Partners (both our local gateway config, and remote shared configs).
    """

    __tablename__ = "as2_partners"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    tenant_id = Column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )  # Null if shared global
    is_local = Column(Boolean, nullable=False, default=False)
    name = Column(String(255), nullable=False)
    as2_id = Column(String(255), nullable=False)
    public_cert_pem = Column(
        Text, nullable=True
    )  # Retained for legacy/external, but vault preferred
    public_cert_vault_ref = Column(String(255), nullable=True)
    private_key_vault_ref = Column(String(255), nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)

    local_partner_id = Column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id", ondelete="CASCADE"), nullable=False
    )
    remote_partner_id = Column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id", ondelete="CASCADE"), nullable=False
    )

    # Core AS2 Networking
    local_url = Column(String(1024), nullable=True)
    remote_url = Column(String(1024), nullable=True)
    credentials_vault_ref = Column(String(255), nullable=True)

    # Core AS2 Protocol Settings
    mdn_type = Column(String(50), nullable=False, default="SYNC")
    mdn_url = Column(String(1024), nullable=True)
    encryption_algorithm = Column(String(50), nullable=False, default="AES256")
    signature_algorithm = Column(String(50), nullable=False, default="SHA256")

    # Advanced OpenAS2 settings
    advanced_flags = Column(JSONB, nullable=True)

    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("local_partner_id", "remote_partner_id", name="uq_as2_partnership"),
    )


class Outbox(GlobalBase, OutboxMixin):
    __tablename__ = "outbox"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

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

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    trace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id = Column(Integer, nullable=False)
    event = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_system_audit_log_tenant_time", "tenant_id", "created_at"),)
