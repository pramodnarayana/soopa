from datetime import datetime
from typing import Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    DateTime,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class OutboxMixin:
    """Shared columns for Outbox across Global and Tenant schemas."""

    @declared_attr
    def idempotency_key(cls) -> Mapped[PyUUID]:
        return mapped_column(UUID(as_uuid=True), nullable=False, unique=True)

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
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(DateTime, default=datetime.utcnow)
