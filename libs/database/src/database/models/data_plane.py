from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr
from sqlalchemy.sql import func

from .common import (
    ConnectionMixin,
    FieldMappingRuleMixin,
    OutboxMixin,
    RouteMixin,
    TradingPartnerMixin,
)


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


class TradingPartner(TenantBase, TenantAwareMixin, TradingPartnerMixin):
    __tablename__ = "trading_partners"

    id = Column(UUID(as_uuid=True), primary_key=True)
    # The tenant model ONLY receives the synchronized schema. No provision_status here.


class Connection(TenantBase, TenantAwareMixin, ConnectionMixin):
    __tablename__ = "connections"

    id = Column(UUID(as_uuid=True), primary_key=True)
    trading_partner_id = Column(UUID(as_uuid=True), nullable=False)


class Route(TenantBase, TenantAwareMixin, RouteMixin):
    __tablename__ = "routes"

    id = Column(UUID(as_uuid=True), primary_key=True)
    source_partner_id = Column(UUID(as_uuid=True), nullable=True)
    target_partner_id = Column(UUID(as_uuid=True), nullable=True)


class FieldMappingRule(TenantBase, TenantAwareMixin, FieldMappingRuleMixin):
    __tablename__ = "field_mapping_rules"

    id = Column(UUID(as_uuid=True), primary_key=True)
    route_id = Column(UUID(as_uuid=True), nullable=False)


# ---------------------------------------------------------------------------
# Domain Models
# ---------------------------------------------------------------------------


class EdiMessage(TenantBase, TenantAwareMixin):
    __tablename__ = "edi_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    trace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    direction = Column(String(50), nullable=False)  # INBOUND, OUTBOUND
    connection_type = Column(String(50), nullable=False)  # AS2, SFTP, FTP
    trading_partner_id = Column(UUID(as_uuid=True), nullable=False)

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

    __table_args__ = (Index("ix_edi_msgs_partner_time", "trading_partner_id", "created_at"),)


class ApiPayload(TenantBase, TenantAwareMixin):
    __tablename__ = "api_payloads"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    trace_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    direction = Column(String(50), nullable=False)  # INBOUND, OUTBOUND
    route_id = Column(UUID(as_uuid=True), nullable=True)

    webhook_url = Column(String(1024), nullable=True)
    http_status_code = Column(Integer, nullable=True)
    target_format = Column(String(50), nullable=True)

    s3_key = Column(String(1024), nullable=False)

    status = Column(String(50), nullable=False, default="RECEIVED")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
            postgresql_where=(OutboxMixin.status == "PENDING"),
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
