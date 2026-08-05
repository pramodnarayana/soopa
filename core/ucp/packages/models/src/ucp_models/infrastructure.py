from datetime import UTC, datetime
from typing import Any

from platform_orm.models.core import UcpBase
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class DatabaseShard(UcpBase):
    __tablename__ = "database_shards"
    ID_PREFIX = "shard"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    dsn: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class ShardRegistry(UcpBase):
    __tablename__ = "shard_registry"

    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.tenants.id", ondelete="CASCADE"), primary_key=True
    )
    app_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.apps.id", ondelete="CASCADE"), primary_key=True
    )
    shard_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ucp.database_shards.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class ScheduledJob(UcpBase):
    __tablename__ = "scheduled_jobs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default={}, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_queue: Mapped[str | None] = mapped_column(String(255), nullable=True)
    app_namespace: Mapped[str | None] = mapped_column(String(255), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    __table_args__ = (
        Index("job_status_next_run_idx", "status", "next_run_at"),
        {"schema": "ucp"},
    )
