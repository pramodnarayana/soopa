import uuid
from datetime import UTC, datetime
from typing import Any

from platform_orm.models.core import UcpBase
from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column


class ScheduledJob(UcpBase):
    __tablename__ = "scheduled_jobs"

    id: Mapped[str] = mapped_column(
        String(128), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, index=True, default="PENDING")

    target_queue: Mapped[str | None] = mapped_column(String, nullable=True)
    app_namespace: Mapped[str | None] = mapped_column(String, nullable=True)
    cron_expression: Mapped[str | None] = mapped_column(String, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String, nullable=True)

    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String, nullable=True)

    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
