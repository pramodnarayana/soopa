"""Dedicated SQLAlchemy ORM models for TMS canonical tables in tenant shards."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ip.engine.adapters.outbound.database.models.base import IpTenantBase


class TmsLoadRecord(IpTenantBase):
    """Dedicated canonical domain table for TMS freight loads."""

    __tablename__ = "tms_loads"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "load_reference_number",
            name="uq_tms_loads_tenant_ref",
        ),
        Index("idx_tms_loads_carrier", "tenant_id", "carrier_scac"),
        Index("idx_tms_loads_status", "tenant_id", "status"),
        Index("idx_tms_loads_trace", "tenant_id", "trace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_replica_id: Mapped[str] = mapped_column(String(64), nullable=False)
    load_reference_number: Mapped[str] = mapped_column(String(128), nullable=False)
    carrier_scac: Mapped[str | None] = mapped_column(String(32), nullable=True)
    origin_city: Mapped[str] = mapped_column(String(128), nullable=False)
    origin_state: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_city: Mapped[str] = mapped_column(String(128), nullable=False)
    destination_state: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="TENDERED")
    total_weight_lbs: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    freight_charge_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pickup_scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivery_scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TmsCarrierRecord(IpTenantBase):
    """Dedicated canonical domain table for TMS freight carriers."""

    __tablename__ = "tms_carriers"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "scac_code",
            name="uq_tms_carriers_tenant_scac",
        ),
        Index("idx_tms_carriers_status", "tenant_id", "status"),
        Index("idx_tms_carriers_trace", "tenant_id", "trace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_replica_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scac_code: Mapped[str] = mapped_column(String(32), nullable=False)
    carrier_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dot_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mc_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    safety_rating: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
