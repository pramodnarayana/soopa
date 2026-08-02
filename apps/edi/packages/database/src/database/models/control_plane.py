import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, registry
from sqlalchemy.sql import text

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

GlobalRegistry = registry()


class UcpBase(DeclarativeBase):
    """
    Base class for models residing in the UCP boundary (e.g., identity, routing).
    Uses the 'ucp' schema in the Global Control Plane DB.
    """

    registry = GlobalRegistry
    __table_args__ = {"schema": "ucp"}


class EdiGlobalBase(DeclarativeBase):
    """
    Base class for models residing in the EDI boundary (e.g., EDI configurations).
    Uses the 'edi' schema in the Global Control Plane DB.
    """

    registry = GlobalRegistry
    __table_args__ = {"schema": "edi"}


class DatabaseShard(UcpBase):
    __tablename__ = "database_shards"

    id: Mapped[str] = mapped_column(
        String(128), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    dsn: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class Tenant(UcpBase):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(
        String(128), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    idp_tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class App(UcpBase):
    __tablename__ = "apps"

    id: Mapped[str] = mapped_column(
        String(128), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)


class ShardRegistry(UcpBase):
    __tablename__ = "shard_registry"

    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.tenants.id", ondelete="CASCADE"), primary_key=True
    )
    app_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.apps.id", ondelete="CASCADE"), primary_key=True
    )
    shard_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.database_shards.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class User(UcpBase):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(128), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    idp_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    __table_args__ = (
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
        {"schema": "ucp"},
    )


class TenantUser(UcpBase):
    __tablename__ = "tenant_users"

    id: Mapped[str] = mapped_column(
        String(128), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user"),
        {"schema": "ucp"},
    )


class ApiToken(UcpBase, TimestampMixin):
    """
    Platform-managed API keys for machine-to-machine (ERP → Platform) authentication.
    Two-part credential: client_id (plaintext, visible) + client_secret (hashed, shown once).
    """

    __tablename__ = "api_tokens"

    id: Mapped[str] = mapped_column(
        String(128), primary_key=True, server_default=text("gen_random_uuid()::text")
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # client_id: stored in plaintext, used for fast indexed lookup and displayed in UI
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # secret_hash: SHA-256 of the raw client_secret; raw value is never stored
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AS2Partner(EdiGlobalBase, AS2PartnerMixin, TimestampMixin):
    """
    Global AS2 Partners (both our local gateway config, and remote shared configs).
    """

    __tablename__ = "as2_partners"

    tenant_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )  # Null if shared global

    __table_args__ = (
        UniqueConstraint("tenant_id", "as2_id", name="uq_tenant_as2_id"),
        Index(
            "uq_global_as2_id", "as2_id", unique=True, postgresql_where=text("tenant_id IS NULL")
        ),
        {"schema": "edi"},
    )


class AS2Partnership(EdiGlobalBase, AS2PartnershipMixin, TimestampMixin):
    """
    OpenAS2 style Partnership (links Local Partner to Remote Partner)
    and stores all MDN and Encryption properties.
    """

    __tablename__ = "as2_partnerships"

    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    local_partner_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("edi.as2_partners.id", ondelete="CASCADE"), nullable=False
    )
    remote_partner_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("edi.as2_partners.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("local_partner_id", "remote_partner_id", name="uq_as2_partnership"),
        {"schema": "edi"},
    )


class ControlPlaneOutbox(EdiGlobalBase, OutboxMixin):
    __tablename__ = "outbox"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (
        Index(
            "ix_global_outbox_pending",
            "status",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        {"schema": "edi"},
    )

    @property
    def body(self) -> dict[str, Any]:
        """Alias for payload to satisfy OutboxEvent protocol."""
        return self.payload


class SystemAuditLog(UcpBase):
    __tablename__ = "system_audit_log"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    __table_args__ = (
        Index("ix_system_audit_log_tenant_time", "tenant_id", "created_at"),
        {"schema": "ucp"},
    )


# ---------------------------------------------------------------------------
# Tenant Protocol & Routing Models (Global Control Plane configuration)
# ---------------------------------------------------------------------------


class SFTPPartner(EdiGlobalBase, SFTPPartnerMixin, TimestampMixin):
    __tablename__ = "sftp_partners"

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)


class Webhook(UcpBase, WebhookMixin, TimestampMixin):
    __tablename__ = "webhooks"

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)


class InboundRoute(EdiGlobalBase, InboundRouteMixin, TimestampMixin):
    __tablename__ = "inbound_routes"

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    webhook_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("ucp.webhooks.id"), nullable=True
    )
    as2_partner_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("edi.as2_partners.id"), nullable=True
    )
    sftp_partner_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("edi.sftp_partners.id"), nullable=True
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
        {"schema": "edi"},
    )


class OutboundRoute(EdiGlobalBase, OutboundRouteMixin, TimestampMixin):
    __tablename__ = "outbound_routes"

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    as2_partner_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("edi.as2_partners.id"), nullable=True
    )
    sftp_partner_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("edi.sftp_partners.id"), nullable=True
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
        {"schema": "edi"},
    )


class OutboundEdiHeader(EdiGlobalBase, OutboundEdiHeaderMixin, TimestampMixin):
    __tablename__ = "outbound_edi_headers"

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    __table_args__ = (
        Index(
            "ix_outbound_edi_headers_unique_trading_partner_id",
            "tenant_id",
            "trading_partner_id",
            unique=True,
        ),
        {"schema": "edi"},
    )
