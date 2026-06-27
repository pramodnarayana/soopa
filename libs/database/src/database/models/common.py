from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID


class TradingPartnerMixin:
    """Shared columns for TradingPartner across Global and Tenant schemas."""

    partner_name = Column(String(255), nullable=False)
    as2_id = Column(String(255), nullable=True)
    direction = Column(String(50), nullable=False)  # INBOUND, OUTBOUND, BOTH
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConnectionMixin:
    """Shared columns for Connection across Global and Tenant schemas."""

    connection_type = Column(String(50), nullable=False)  # AS2, SFTP, FTP, WEBHOOK
    host = Column(String(1024), nullable=True)
    port = Column(Integer, nullable=True)
    direction = Column(String(50), nullable=False)  # INBOUND, OUTBOUND
    credentials_vault_ref = Column(String(255), nullable=False)
    poll_interval_secs = Column(Integer, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RouteMixin:
    """Shared columns for Route across Global and Tenant schemas."""

    source_format = Column(String(50), nullable=False)
    target_format = Column(String(50), nullable=False)
    transaction_type = Column(String(50), nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class FieldMappingRuleMixin:
    """Shared columns for FieldMappingRule across Global and Tenant schemas."""

    source_path = Column(Text, nullable=False)
    dest_path = Column(Text, nullable=False)
    required = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)


class OutboxMixin:
    """Shared columns for Outbox across Global and Tenant schemas."""

    idempotency_key = Column(UUID(as_uuid=True), nullable=False, unique=True)
    event_type = Column(String(100), nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(String(50), nullable=False, default="PENDING")
    created_at = Column(DateTime, default=datetime.utcnow)
