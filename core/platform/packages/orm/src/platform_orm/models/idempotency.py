from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .core import UcpBase


class IdempotencyResult(UcpBase):
    """
    Stores the result of an idempotent operation per the Stripe/AWS idempotency standard.
    Keys expire after 24 hours and use INSERT ... ON CONFLICT DO NOTHING for lock-free concurrency.
    """

    __tablename__ = "idempotency_results"
    __table_args__ = {"schema": "ucp"}

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    # Lifecycle: IN_PROGRESS → COMPLETED | ERROR
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="IN_PROGRESS")
    response_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
