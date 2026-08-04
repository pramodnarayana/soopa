from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class OutboxMixin:
    """Shared columns for Outbox across Global and Tenant schemas."""

    @declared_attr
    def idempotency_key(cls) -> Mapped[str]:
        return mapped_column(String(128), nullable=False, unique=True)

    @declared_attr
    def event_type(cls) -> Mapped[str]:
        return mapped_column(String(100), nullable=False)

    @declared_attr
    def payload(cls) -> Mapped[dict[str, Any]]:
        return mapped_column(JSONB, nullable=False)

    @declared_attr
    def status(cls) -> Mapped[str]:
        return mapped_column(String(50), nullable=False, default="PENDING")

    @declared_attr
    def attempts(cls) -> Mapped[int]:
        return mapped_column(Integer, default=0)

    @declared_attr
    def published_at(cls) -> Mapped[datetime | None]:
        return mapped_column(DateTime(timezone=True), nullable=True)

    @declared_attr
    def error_reason(cls) -> Mapped[str | None]:
        return mapped_column(String, nullable=True)

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    @declared_attr
    def owner_token(cls) -> Mapped[str | None]:
        return mapped_column(String(128), nullable=True)

    @declared_attr
    def lease_expires_at(cls) -> Mapped[datetime | None]:
        return mapped_column(DateTime(timezone=True), nullable=True)


class TimestampMixin:
    """Provides created_at and updated_at for configuration tables."""

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            onupdate=lambda: datetime.now(UTC),
        )
