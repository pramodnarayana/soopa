from datetime import UTC, datetime

from outbox.domain.constants import OutboxStatus
from seedwork.domain.types import JsonDict
from seedwork.events import EventProcessingLane
from sqlalchemy import (
    DateTime,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declarative_mixin, declared_attr, mapped_column


@declarative_mixin
class OutboxMixin:
    """Shared SQLAlchemy 2.0 columns for Outbox tables across Global and Tenant schemas."""

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lane: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EventProcessingLane.REALTIME.value,
        server_default=text("'realtime'"),
    )
    payload: Mapped[JsonDict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=OutboxStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    owner_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TimestampMixin:
    """Provides created_at and updated_at for configuration tables."""

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:

        return mapped_column(
            DateTime(timezone=True), server_default=text("now()"), default=lambda: datetime.now(UTC)
        )

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:

        return mapped_column(
            DateTime(timezone=True),
            server_default=text("now()"),
            default=lambda: datetime.now(UTC),
            onupdate=lambda: datetime.now(UTC),
        )


class SoftDeleteMixin:
    """Provides soft deletion capabilities for models."""

    @declared_attr
    def deleted_at(cls) -> Mapped[datetime | None]:
        return mapped_column(DateTime(timezone=True), nullable=True)

    @declared_attr
    def deleted_by(cls) -> Mapped[str | None]:
        return mapped_column(String, nullable=True)


class ProcessedEventMixin:
    """Shared columns for tenant-scoped idempotency ledger tables (processed_events)."""

    @declared_attr
    def tenant_id(cls) -> Mapped[str]:
        return mapped_column(String(128), nullable=False)

    @declared_attr
    def idempotency_key(cls) -> Mapped[str]:
        return mapped_column(String(255), primary_key=True, nullable=False)

    @declared_attr
    def processed_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
            default=lambda: datetime.now(UTC),
        )
