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

from .common import OutboxMixin


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
        return mapped_column(Integer, nullable=False, index=True)


# ---------------------------------------------------------------------------
# Replicated Config Models (Read-Only for Workers)
# ---------------------------------------------------------------------------


class AS2Partner(TenantBase, TenantAwareMixin):
    __tablename__ = "as2_partners"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    is_local: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    as2_id: Mapped[str] = mapped_column(String(255), nullable=False)
    public_cert_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_cert_vault_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    private_key_vault_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    prev_public_cert_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    prev_public_cert_vault_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prev_private_key_vault_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, default=False)


class AS2Partnership(TenantBase, TenantAwareMixin):
    __tablename__ = "as2_partnerships"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    local_partner_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id", ondelete="CASCADE"), nullable=False
    )
    remote_partner_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id", ondelete="CASCADE"), nullable=False
    )

    credentials_vault_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    mdn_type: Mapped[str] = mapped_column(String(50), nullable=False, default="SYNC")
    mdn_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    encryption_algorithm: Mapped[str] = mapped_column(String(50), nullable=False, default="AES256")
    signature_algorithm: Mapped[str] = mapped_column(String(50), nullable=False, default="SHA256")

    advanced_flags: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------------------
# Tenant Protocol & Routing Models
# ---------------------------------------------------------------------------


class SFTPPartner(TenantBase, TenantAwareMixin):
    __tablename__ = "sftp_partners"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    host: Mapped[str] = mapped_column(String(1024), nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=22)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    host_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    inbound_remote_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    outbound_remote_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    password_encrypted: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    credentials_vault_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)


class Webhook(TenantBase, TenantAwareMixin):
    __tablename__ = "webhooks"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    auth_header_vault_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)


class InboundRoute(TenantBase, TenantAwareMixin):
    __tablename__ = "inbound_routes"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    isa_sender_id: Mapped[str] = mapped_column(String(255), nullable=False)
    isa_receiver_id: Mapped[str] = mapped_column(String(255), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    processing_mode: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="TRANSLATE"
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
    active: Mapped[bool] = mapped_column(Boolean, default=False)

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


class OutboundRoute(TenantBase, TenantAwareMixin):
    __tablename__ = "outbound_routes"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    isa_sender_id: Mapped[str] = mapped_column(String(255), nullable=False)
    isa_receiver_id: Mapped[str] = mapped_column(String(255), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    processing_mode: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="TRANSLATE"
    )
    as2_partner_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id"), nullable=True
    )
    sftp_partner_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sftp_partners.id"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        CheckConstraint(
            "(as2_partner_id IS NOT NULL)::int + (sftp_partner_id IS NOT NULL)::int = 1",
            name="chk_outbound_routes_exactly_one_dest",
        ),
        Index(
            "ix_outbound_routes_unique_active",
            "tenant_id",
            "isa_sender_id",
            "isa_receiver_id",
            "transaction_type",
            unique=True,
            postgresql_where=text("active = true"),
        ),
    )


# ---------------------------------------------------------------------------
# Domain Models
# ---------------------------------------------------------------------------


class EdiMessage(TenantBase, TenantAwareMixin):
    __tablename__ = "edi_messages"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    trace_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(50), nullable=False)  # INBOUND, OUTBOUND
    connection_type: Mapped[str] = mapped_column(String(50), nullable=False)  # AS2, SFTP, FTP

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

    interchange_control_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transaction_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    format_standard: Mapped[str | None] = mapped_column(String(50), nullable=True)

    edi_data: Mapped[str] = mapped_column(SanitizedText, nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="RECEIVED")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (Index("ix_edi_msgs_sender_recv", "sender_id", "receiver_id", "created_at"),)


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

    request: Mapped[str] = mapped_column(String(1024), nullable=False)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    headers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="RECEIVED")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
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
