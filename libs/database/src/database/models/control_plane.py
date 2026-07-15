from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func, text

from .common import OutboxMixin, TimestampMixin
from .replicated_mixins import (
    AS2PartnerMixin,
    AS2PartnershipMixin,
    InboundRouteMixin,
    OutboundEdiHeaderMixin,
    OutboundRouteMixin,
    SFTPPartnerMixin,
    WebhookMixin,
)


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


class ApiToken(GlobalBase, TimestampMixin):
    """
    Platform-managed API keys for machine-to-machine (ERP → Platform) authentication.
    Two-part credential: client_id (plaintext, visible) + client_secret (hashed, shown once).
    """

    __tablename__ = "api_tokens"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # client_id: stored in plaintext, used for fast indexed lookup and displayed in UI
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # secret_hash: SHA-256 of the raw client_secret; raw value is never stored
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AS2Partner(GlobalBase, AS2PartnerMixin, TimestampMixin):
    """
    Global AS2 Partners (both our local gateway config, and remote shared configs).
    """

    __tablename__ = "as2_partners"

    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )  # Null if shared global
    is_local: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "as2_id", name="uq_tenant_as2_id"),
        Index(
            "uq_global_as2_id", "as2_id", unique=True, postgresql_where=text("tenant_id IS NULL")
        ),
    )


class AS2Partnership(GlobalBase, AS2PartnershipMixin, TimestampMixin):
    """
    OpenAS2 style Partnership (links Local Partner to Remote Partner)
    and stores all MDN and Encryption properties.
    """

    __tablename__ = "as2_partnerships"

    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )

    local_partner_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id", ondelete="CASCADE"), nullable=False
    )
    remote_partner_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id", ondelete="CASCADE"), nullable=False
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


# ---------------------------------------------------------------------------
# Tenant Protocol & Routing Models (Global Control Plane configuration)
# ---------------------------------------------------------------------------


class SFTPPartner(GlobalBase, SFTPPartnerMixin, TimestampMixin):
    __tablename__ = "sftp_partners"

    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )


class Webhook(GlobalBase, WebhookMixin, TimestampMixin):
    __tablename__ = "webhooks"

    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )


class InboundRoute(GlobalBase, InboundRouteMixin, TimestampMixin):
    __tablename__ = "inbound_routes"

    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    webhook_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhooks.id"), nullable=True
    )
    as2_partner_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id"), nullable=True
    )
    sftp_partner_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sftp_partners.id"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "(webhook_id IS NOT NULL)::int + (as2_partner_id IS NOT NULL)::int + (sftp_partner_id IS NOT NULL)::int = 1",
            name="chk_inbound_routes_exactly_one_dest",
        ),
        Index(
            "ix_inbound_routes_unique_active",
            "tenant_id",
            "isa_sender_id",
            "isa_receiver_id",
            "transaction_type",
            unique=True,
            postgresql_where=text("active = true"),
        ),
    )


class OutboundRoute(GlobalBase, OutboundRouteMixin, TimestampMixin):
    __tablename__ = "outbound_routes"

    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    as2_partner_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id"), nullable=True
    )
    sftp_partner_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sftp_partners.id"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "(as2_partner_id IS NOT NULL)::int + (sftp_partner_id IS NOT NULL)::int = 1",
            name="chk_outbound_routes_exactly_one_dest",
        ),
        Index(
            "ix_outbound_routes_unique_trading_partner_id",
            "tenant_id",
            "trading_partner_id",
            unique=True,
            postgresql_where=text("active = true"),
        ),
    )


class OutboundEdiHeader(GlobalBase, OutboundEdiHeaderMixin, TimestampMixin):
    __tablename__ = "outbound_edi_headers"

    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    __table_args__ = (
        Index(
            "ix_outbound_edi_headers_unique_trading_partner_id",
            "tenant_id",
            "trading_partner_id",
            unique=True,
        ),
    )
