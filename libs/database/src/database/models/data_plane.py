from datetime import datetime
from typing import Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from sqlalchemy.sql import func, text
from sqlalchemy.types import TypeDecorator

from .common import OutboxMixin, TimestampMixin
from .replicated_mixins import (
    AS2PartnerMixin,
    AS2PartnershipMixin,
    InboundRouteMixin,
    OutboundRouteMixin,
    SFTPPartnerMixin,
    WebhookMixin,
)


class SanitizedText(TypeDecorator):  # type: ignore
    """
    Enterprise-grade Text type that enforces PostgreSQL compliance
    by automatically stripping NUL bytes (\\x00) and safely decoding
    bytes with errors='replace'.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):  # type: ignore
        if value is None:
            return value
        if isinstance(value, bytes):
            return value.replace(b"\x00", b"").decode("utf-8", errors="replace")
        elif not isinstance(value, str):
            value = str(value)
        return value.replace("\x00", "")


class TenantBase(DeclarativeBase):
    pass


class TenantAwareMixin:
    """
    Mixin that adds a `tenant_id` to all tenant-scoped tables.
    Essential for Row-Level Security (RLS) enforcement if needed.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[int]:
        return mapped_column(
            Integer,
            server_default=text("current_setting('app.current_tenant')::int"),
            nullable=False,
            index=True,
        )


# ---------------------------------------------------------------------------
# Replicated Config Models (Read-Only for Workers)
# ---------------------------------------------------------------------------


class AS2Partner(TenantBase, TenantAwareMixin, AS2PartnerMixin, TimestampMixin):
    __tablename__ = "as2_partners"


class AS2Partnership(TenantBase, TenantAwareMixin, AS2PartnershipMixin, TimestampMixin):
    __tablename__ = "as2_partnerships"

    local_partner_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id", ondelete="CASCADE"), nullable=False
    )
    remote_partner_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id", ondelete="CASCADE"), nullable=False
    )


# ---------------------------------------------------------------------------
# Tenant Protocol & Routing Models
# ---------------------------------------------------------------------------


class SFTPPartner(TenantBase, TenantAwareMixin, SFTPPartnerMixin, TimestampMixin):
    __tablename__ = "sftp_partners"


class Webhook(TenantBase, TenantAwareMixin, WebhookMixin, TimestampMixin):
    __tablename__ = "webhooks"


class InboundRoute(TenantBase, TenantAwareMixin, InboundRouteMixin, TimestampMixin):
    __tablename__ = "inbound_routes"

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


class OutboundRoute(TenantBase, TenantAwareMixin, OutboundRouteMixin, TimestampMixin):
    __tablename__ = "outbound_routes"

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


# ---------------------------------------------------------------------------
# Domain Models
# ---------------------------------------------------------------------------


class EdiMessage(TenantBase, TenantAwareMixin, TimestampMixin):
    __tablename__ = "edi_messages"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    trace_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(50), nullable=False)  # INBOUND, OUTBOUND
    connection_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # AS2, SFTP, FTP

    sender_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receiver_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mdn_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mdn_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mdn_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signature_algorithm: Mapped[str | None] = mapped_column(String(50), nullable=True)
    encryption_algorithm: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_resend: Mapped[bool] = mapped_column(Boolean, default=False)
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str | None] = mapped_column(String(255), nullable=True)
    msg_headers: Mapped[str | None] = mapped_column(Text, nullable=True)
    outbound_route_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outbound_routes.id"), nullable=True, index=True
    )

    interchange_control_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transaction_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    format_standard: Mapped[str | None] = mapped_column(String(50), nullable=True)

    edi_data: Mapped[str | None] = mapped_column(SanitizedText, nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="RECEIVED")

    __table_args__ = (
        Index("ix_edi_msgs_sender_recv", "sender_id", "receiver_id", "created_at"),
        CheckConstraint(
            "(edi_data IS NOT NULL OR storage_uri IS NOT NULL)",
            name="chk_edi_msg_data_or_uri",
        ),
    )


class EdiJson(TenantBase, TenantAwareMixin):
    __tablename__ = "edi_json"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    trace_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(50), nullable=False)  # INBOUND, OUTBOUND

    outbound_route_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outbound_routes.id"), nullable=True, index=True
    )
    transaction_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    standard: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sender_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receiver_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    business_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="TRANSLATED")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_edi_json_business_metadata", "business_metadata", postgresql_using="gin"),
        Index("ix_edi_json_sender_recv", "sender_id", "receiver_id", "created_at"),
        CheckConstraint(
            "(payload IS NOT NULL OR storage_uri IS NOT NULL)",
            name="chk_edi_json_data_or_uri",
        ),
    )


class ApiGateway(TenantBase, TenantAwareMixin):
    __tablename__ = "api_gateway"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    trace_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(50), nullable=False)  # INBOUND, OUTBOUND
    transaction_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    webhook_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    http_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_format: Mapped[str | None] = mapped_column(String(50), nullable=True)

    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    headers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="RECEIVED")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "(payload IS NOT NULL OR storage_uri IS NOT NULL)",
            name="chk_apigw_data_or_uri",
        ),
    )


class Job(TenantBase, TenantAwareMixin):
    __tablename__ = "jobs"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    trace_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # TRANSLATE, DELIVER
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Outbox(TenantBase, TenantAwareMixin, OutboxMixin):
    __tablename__ = "outbox"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index(
            "ix_tenant_outbox_pending",
            "status",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
    )


class ProcessedEvent(TenantBase, TenantAwareMixin):
    __tablename__ = "processed_events"

    idempotency_key: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(TenantBase, TenantAwareMixin):
    __tablename__ = "audit_log"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    trace_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    step: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AckReceipt(TenantBase, TenantAwareMixin):
    __tablename__ = "ack_receipts"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    trace_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # MDN, 997, CONTRL
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
