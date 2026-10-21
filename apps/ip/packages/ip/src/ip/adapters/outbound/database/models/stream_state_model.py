"""SQLAlchemy ORM model for connection_stream_states table."""

from __future__ import annotations

from datetime import datetime

from ip.adapters.outbound.database.models.base import IpBase
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class ConnectionStreamStateRecord(IpBase):
    """Database record representation of the connection_stream_states table."""

    __tablename__ = "connection_stream_states"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "connection_id",
            "stream_name",
            name="uq_ip_stream_state_tenant_conn_stream",
        ),
        Index("idx_ip_stream_state_conn", "tenant_id", "connection_id"),
        {"schema": "ip"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    connection_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ip.connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    stream_name: Mapped[str] = mapped_column(String(128), nullable=False)
    cursor_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cursor_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    records_synced_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
