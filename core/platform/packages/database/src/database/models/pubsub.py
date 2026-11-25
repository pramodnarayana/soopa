"""SQLAlchemy ORM models for the Platform Pub/Sub PostgreSQL transport (`pubsub` schema)."""

from __future__ import annotations

from datetime import UTC, datetime

from outbox.domain.constants import OutboxStatus
from seedwork.domain.types import JsonDict
from seedwork.events import EventProcessingLane
from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, asc, desc, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.models.core import PubSubBase


class PlatformQueueMessage(PubSubBase):
    """Durable, cross-container PostgreSQL queue table backing `db://<queue_name>` URIs.

    Uses a composite primary key `(queue_name, id)` so a single domain event fanned out across
    multiple subscriber queues preserves its exact original `EventEnvelope.id` in every queue
    while guaranteeing per-queue deduplication.
    """

    __tablename__ = "platform_queue_messages"

    queue_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lane: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EventProcessingLane.REALTIME.value,
        server_default=text("'realtime'"),
    )
    payload: Mapped[JsonDict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=OutboxStatus.PENDING.value,
        server_default=text("'PENDING'"),
    )
    attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, default=5, server_default=text("5"), nullable=False
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    __table_args__ = (
        Index(
            "ix_platform_queue_pending",
            "queue_name",
            desc("lane"),
            asc("created_at"),
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index(
            "ix_platform_queue_processing_lease",
            "queue_name",
            "lease_expires_at",
            postgresql_where=text("status = 'PROCESSING'"),
        ),
        Index(
            "ix_platform_queue_processed_cleanup",
            "created_at",
            postgresql_where=text("status IN ('PROCESSED', 'COMPLETED')"),
        ),
        Index(
            "uq_platform_queue_name_idempotency",
            "queue_name",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        {"schema": "pubsub"},
    )


class PlatformTopicSubscription(PubSubBase):
    """Decoupled consumer-registered topic subscription table backing `db://topic/<topic_name>`.

    Producers publish strictly to logical topic names without knowing subscriber queue topologies.
    Consumers self-register their target queue and optional `event_types` filter on startup.
    """

    __tablename__ = "platform_topic_subscriptions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    topic_name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_queue: Mapped[str] = mapped_column(String(255), nullable=False)
    event_types: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
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

    __table_args__ = (
        Index(
            "ix_platform_topic_sub_active_topic",
            "topic_name",
            postgresql_where=text("is_active IS TRUE"),
        ),
        Index(
            "uq_platform_topic_sub_topic_queue",
            "topic_name",
            "target_queue",
            unique=True,
        ),
        {"schema": "pubsub"},
    )
