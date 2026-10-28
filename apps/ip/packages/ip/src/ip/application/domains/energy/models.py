"""Dedicated SQLAlchemy ORM models for Energy MDM canonical tables in tenant shards."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ip.application.domains.energy.canonical import (
    MeterReadingQualityFlag,
    ServicePointStatus,
)
from ip.engine.adapters.outbound.database.models.base import IpTenantBase


class MdmMeterReadingRecord(IpTenantBase):
    """Dedicated canonical domain table for Smart Grid AMI interval meter readings."""

    __tablename__ = "mdm_meter_readings"
    __table_args__ = (
        PrimaryKeyConstraint("id", "reading_timestamp"),
        Index(
            "idx_mdm_readings_meter_ts",
            "tenant_id",
            "meter_serial_number",
            "reading_timestamp",
        ),
        Index("idx_mdm_readings_sp", "tenant_id", "service_point_id"),
        Index("idx_mdm_readings_trace", "tenant_id", "trace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_replica_id: Mapped[str] = mapped_column(String(64), nullable=False)
    transformation_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="energy.ami_meter_reading"
    )
    transformation_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    meter_serial_number: Mapped[str] = mapped_column(String(128), nullable=False)
    service_point_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reading_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    kwh_delivered: Mapped[float] = mapped_column(Float, nullable=False)
    kwh_received: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    voltage_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_flag: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MeterReadingQualityFlag.VALIDATED.value,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MdmServicePointRecord(IpTenantBase):
    """Dedicated canonical domain table for Energy utility service points."""

    __tablename__ = "mdm_service_points"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "service_point_external_id",
            name="uq_mdm_service_point_tenant_ext",
        ),
        Index("idx_mdm_sp_meter", "tenant_id", "meter_serial_number"),
        Index("idx_mdm_sp_trace", "tenant_id", "trace_id"),
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
    transformation_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="energy.ami_service_point"
    )
    transformation_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    service_point_external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    meter_serial_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    customer_external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    service_address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    grid_region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ServicePointStatus.ACTIVE.value,
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
