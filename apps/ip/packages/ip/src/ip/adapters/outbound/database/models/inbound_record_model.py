"""SQLAlchemy ORM model for inbound_records table (Layer 1 Inbound Gateway Audit)."""

from __future__ import annotations

from datetime import datetime

from ip.adapters.outbound.database.models.base import IpBase
from ip.domain.types import JsonDict
from sqlalchemy import DateTime, Index, Integer, PrimaryKeyConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class InboundRecordModel(IpBase):
    """Database record representation of the inbound_records audit table."""

    __tablename__ = "inbound_records"
    __table_args__ = (
        PrimaryKeyConstraint("id", "received_at"),
        Index("idx_inbound_trace", "tenant_id", "business_trace_id"),
        Index("idx_inbound_corr", "tenant_id", "business_correlation_id"),
        Index("idx_inbound_conn", "tenant_id", "connection_id"),
        Index("idx_inbound_app", "tenant_id", "app_id"),
        {"schema": "ip"},
    )

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    business_trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    business_correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stream_name: Mapped[str] = mapped_column(String(128), nullable=False)
    request_headers: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, default=dict)
    request_body: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    request_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    request_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_headers: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    response_body: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    response_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
