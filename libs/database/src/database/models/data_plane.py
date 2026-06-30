from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr
from sqlalchemy.sql import func, text

from .common import OutboxMixin


class TenantBase(DeclarativeBase):
    __allow_unmapped__ = True


class TenantAwareMixin:
    """
    Mixin that adds a `tenant_id` to all tenant-scoped tables.
    Essential for Row-Level Security (RLS) enforcement if needed.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[int]:
        from sqlalchemy.orm import mapped_column

        return mapped_column(Integer, nullable=False, index=True)


# ---------------------------------------------------------------------------
# Replicated Config Models (Read-Only for Workers)
# ---------------------------------------------------------------------------


class AS2Partner(TenantBase, TenantAwareMixin):
    __tablename__ = "as2_partners"

    id = Column(UUID(as_uuid=True), primary_key=True)
    is_local = Column(Boolean, nullable=False, default=False)
    name = Column(String(255), nullable=False)
    as2_id = Column(String(255), nullable=False)
    public_cert_pem = Column(Text, nullable=True)
    public_cert_vault_ref = Column(String(255), nullable=True)
    private_key_vault_ref = Column(String(255), nullable=True)
    active = Column(Boolean, default=True)


class AS2Partnership(TenantBase, TenantAwareMixin):
    __tablename__ = "as2_partnerships"

    id = Column(UUID(as_uuid=True), primary_key=True)

    local_partner_id = Column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id", ondelete="CASCADE"), nullable=False
    )
    remote_partner_id = Column(
        UUID(as_uuid=True), ForeignKey("as2_partners.id", ondelete="CASCADE"), nullable=False
    )

    local_url = Column(String(1024), nullable=True)
    remote_url = Column(String(1024), nullable=True)
    credentials_vault_ref = Column(String(255), nullable=True)

    mdn_type = Column(String(50), nullable=False, default="SYNC")
    mdn_url = Column(String(1024), nullable=True)
    encryption_algorithm = Column(String(50), nullable=False, default="AES256")
    signature_algorithm = Column(String(50), nullable=False, default="SHA256")

    advanced_flags = Column(JSONB, nullable=True)

    active = Column(Boolean, default=True)


# ---------------------------------------------------------------------------
# Tenant Protocol & Routing Models
# ---------------------------------------------------------------------------


class SFTPPartner(TenantBase, TenantAwareMixin):
    __tablename__ = "sftp_partners"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name = Column(String(255), nullable=False)
    host = Column(String(1024), nullable=False)
    port = Column(Integer, default=22)
    username = Column(String(255), nullable=False)
    remote_path = Column(String(1024), nullable=True)
    credentials_vault_ref = Column(String(255), nullable=False)
    active = Column(Boolean, default=True)


class WebhookPartner(TenantBase, TenantAwareMixin):
    __tablename__ = "webhook_partners"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name = Column(String(255), nullable=False)
    url = Column(String(1024), nullable=False)
    auth_header_vault_ref = Column(String(255), nullable=True)
    active = Column(Boolean, default=True)


class InboundRoute(TenantBase, TenantAwareMixin):
    __tablename__ = "inbound_routes"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    isa_sender_id = Column(String(255), nullable=False)
    isa_receiver_id = Column(String(255), nullable=False)
    transaction_type = Column(String(50), nullable=False)
    webhook_partner_id = Column(
        UUID(as_uuid=True), ForeignKey("webhook_partners.id"), nullable=True
    )
    as2_partner_id = Column(UUID(as_uuid=True), ForeignKey("as2_partners.id"), nullable=True)
    sftp_partner_id = Column(UUID(as_uuid=True), ForeignKey("sftp_partners.id"), nullable=True)
    active = Column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint(
            "(webhook_partner_id IS NOT NULL)::int + (as2_partner_id IS NOT NULL)::int + (sftp_partner_id IS NOT NULL)::int = 1",
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

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    isa_sender_id = Column(String(255), nullable=False)
    isa_receiver_id = Column(String(255), nullable=False)
    transaction_type = Column(String(50), nullable=False)
    as2_partner_id = Column(UUID(as_uuid=True), ForeignKey("as2_partners.id"), nullable=True)
    sftp_partner_id = Column(UUID(as_uuid=True), ForeignKey("sftp_partners.id"), nullable=True)
    active = Column(Boolean, default=True)

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

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    trace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    direction = Column(String(50), nullable=False)  # INBOUND, OUTBOUND
    connection_type = Column(String(50), nullable=False)  # AS2, SFTP, FTP

    sender_id = Column(String(255), nullable=True)
    receiver_id = Column(String(255), nullable=True)
    as2_message_id = Column(String(255), nullable=True)
    interchange_control_no = Column(String(255), nullable=True)
    transaction_type = Column(String(50), nullable=True)
    format_standard = Column(String(50), nullable=True)

    s3_key = Column(String(1024), nullable=False)
    file_size_bytes = Column(BigInteger, nullable=True)

    status = Column(String(50), nullable=False, default="RECEIVED")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("ix_edi_msgs_sender_recv", "sender_id", "receiver_id", "created_at"),)


class ApiPayload(TenantBase, TenantAwareMixin):
    __tablename__ = "api_payloads"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    trace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    direction = Column(String(50), nullable=False)  # INBOUND, OUTBOUND
    transaction_type = Column(String(50), nullable=True)
    inbound_route_id = Column(UUID(as_uuid=True), ForeignKey("inbound_routes.id"), nullable=True)
    outbound_route_id = Column(UUID(as_uuid=True), ForeignKey("outbound_routes.id"), nullable=True)

    webhook_url = Column(String(1024), nullable=True)
    http_status_code = Column(Integer, nullable=True)
    target_format = Column(String(50), nullable=True)

    s3_key = Column(String(1024), nullable=False)

    status = Column(String(50), nullable=False, default="RECEIVED")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "(inbound_route_id IS NOT NULL AND outbound_route_id IS NULL) OR "
            "(inbound_route_id IS NULL AND outbound_route_id IS NOT NULL)",
            name="chk_api_payload_single_route",
        ),
    )


class Job(TenantBase, TenantAwareMixin):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    trace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # TRANSLATE, DELIVER
    status = Column(String(50), nullable=False, default="PENDING")
    attempt_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Outbox(TenantBase, TenantAwareMixin, OutboxMixin):
    __tablename__ = "outbox"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    attempts = Column(Integer, default=0)
    published_at = Column(DateTime, nullable=True)

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

    idempotency_key = Column(UUID(as_uuid=True), primary_key=True)
    processed_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(TenantBase, TenantAwareMixin):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    trace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    step = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False)
    duration_ms = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AckReceipt(TenantBase, TenantAwareMixin):
    __tablename__ = "ack_receipts"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    trace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # MDN, 997, CONTRL
    status = Column(String(50), nullable=False)
    raw_content = Column(Text, nullable=True)
    received_at = Column(DateTime, default=datetime.utcnow)
