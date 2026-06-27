from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func, text

from .common import (
    ConnectionMixin,
    FieldMappingRuleMixin,
    OutboxMixin,
    RouteMixin,
    TradingPartnerMixin,
)


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


class TradingPartner(GlobalBase, TradingPartnerMixin):
    __tablename__ = "trading_partners"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    # Global-specific fields (Provisioning metadata)
    provision_status = Column(String(50), nullable=False, default="PROVISIONING")
    provisioned_at = Column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("id", "tenant_id", name="uq_tp_tenant"),)


class Connection(GlobalBase, ConnectionMixin):
    __tablename__ = "connections"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    trading_partner_id = Column(UUID(as_uuid=True), nullable=False)
    tenant_id = Column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["trading_partner_id", "tenant_id"],
            ["trading_partners.id", "trading_partners.tenant_id"],
            ondelete="CASCADE",
        ),
    )


class Route(GlobalBase, RouteMixin):
    __tablename__ = "routes"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    source_partner_id = Column(UUID(as_uuid=True), nullable=True)
    target_partner_id = Column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["source_partner_id", "tenant_id"],
            ["trading_partners.id", "trading_partners.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["target_partner_id", "tenant_id"],
            ["trading_partners.id", "trading_partners.tenant_id"],
            ondelete="CASCADE",
        ),
    )


class FieldMappingRule(GlobalBase, FieldMappingRuleMixin):
    __tablename__ = "field_mapping_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    route_id = Column(
        UUID(as_uuid=True), ForeignKey("routes.id", ondelete="CASCADE"), nullable=False
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
            postgresql_where=(OutboxMixin.status == "PENDING"),
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
