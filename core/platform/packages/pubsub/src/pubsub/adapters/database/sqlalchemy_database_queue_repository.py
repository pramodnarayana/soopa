"""SQLAlchemy 2.0 ORM adapter for the durable PostgreSQL Pub/Sub Engine (`pubsub` schema)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import structlog
from database.models.pubsub import PlatformQueueMessage, PlatformTopicSubscription
from outbox.domain.constants import OutboxStatus
from seedwork.events import EventEnvelope, EventProcessingLane
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import case, delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from pubsub.ports.database_queue_port import DatabaseQueuePort

logger = structlog.get_logger(__name__)

SessionScopeFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class SqlAlchemyDatabaseQueueRepository(DatabaseQueuePort):
    """Durable, ACID-guaranteed PostgreSQL queue & topic fan-out engine using `FOR UPDATE SKIP LOCKED`."""

    _CLEANUP_CHUNK_SIZE: int = 1000
    _DEFAULT_MAX_ATTEMPTS: int = 5
    _BASE_RETRY_BACKOFF_SECONDS: int = 10
    _MAX_RETRY_BACKOFF_SECONDS: int = 300

    def __init__(
        self,
        session_factory: SessionScopeFactory,
        *,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        base_retry_backoff_seconds: int = _BASE_RETRY_BACKOFF_SECONDS,
        max_retry_backoff_seconds: int = _MAX_RETRY_BACKOFF_SECONDS,
    ) -> None:
        self._session_scope = session_factory
        self._max_attempts = max_attempts
        self._base_retry_backoff_seconds = base_retry_backoff_seconds
        self._max_retry_backoff_seconds = max_retry_backoff_seconds

    @staticmethod
    def _to_envelope(row: PlatformQueueMessage) -> EventEnvelope:
        """Explicit Data Mapper from ORM `PlatformQueueMessage` to domain `EventEnvelope`."""
        lane_val = (
            EventProcessingLane.BULK
            if row.lane == EventProcessingLane.BULK.value
            else EventProcessingLane.REALTIME
        )
        return EventEnvelope(
            id=row.id,
            source=row.source,
            event_type=row.event_type,
            tenant_id=row.tenant_id,
            idempotency_key=row.idempotency_key,
            payload=dict(row.payload),
            trace_id=row.trace_id,
            correlation_id=row.correlation_id,
            lane=lane_val,
        )

    def _build_queue_row(
        self,
        queue_name: str,
        event: EventEnvelope,
        now: datetime,
    ) -> dict[str, object]:
        return {
            "queue_name": queue_name,
            "id": event.id,
            "tenant_id": event.tenant_id,
            "source": event.source,
            "event_type": event.event_type,
            "idempotency_key": event.idempotency_key,
            "trace_id": event.trace_id,
            "correlation_id": event.correlation_id,
            "lane": event.lane.value,
            "payload": dict(event.payload),
            "status": OutboxStatus.PENDING.value,
            "attempts": 0,
            "max_attempts": self._max_attempts,
            "created_at": now,
            "updated_at": now,
        }

    async def enqueue(self, queue_name: str, event: EventEnvelope) -> None:
        await self.enqueue_batch(queue_name, [event])

    async def enqueue_batch(self, queue_name: str, events: Sequence[EventEnvelope]) -> list[str]:
        if not events:
            return []

        now = datetime.now(UTC)
        rows = [self._build_queue_row(queue_name, event, now) for event in events]

        async with self._session_scope() as session:
            stmt = pg_insert(PlatformQueueMessage).values(rows).on_conflict_do_nothing()
            await session.execute(stmt)
            await session.commit()

        logger.info(
            "database_queue_batch_enqueued",
            queue_name=queue_name,
            count=len(events),
        )
        return [e.id for e in events]

    async def register_subscription(
        self,
        topic_name: str,
        target_queue: str,
        *,
        event_types: Sequence[str] | None = None,
    ) -> None:
        now = datetime.now(UTC)
        normalized_types: list[str] | None = list(event_types) if event_types else None
        async with self._session_scope() as session:
            stmt = (
                pg_insert(PlatformTopicSubscription)
                .values(
                    id=generate_id(SystemIdPrefix.GENERIC),
                    topic_name=topic_name,
                    target_queue=target_queue,
                    event_types=normalized_types,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["topic_name", "target_queue"],
                    set_={
                        "event_types": normalized_types,
                        "is_active": True,
                        "updated_at": now,
                    },
                )
            )
            await session.execute(stmt)
            await session.commit()

        logger.info(
            "database_topic_subscription_registered",
            topic_name=topic_name,
            target_queue=target_queue,
            event_types=normalized_types,
        )

    async def publish_to_topic(self, topic_name: str, event: EventEnvelope) -> list[str]:
        await self.publish_batch_to_topic(topic_name, [event])
        return [event.id]

    @staticmethod
    def _matches_event_filter(event_type: str, patterns: Sequence[str] | None) -> bool:
        """Evaluates exact, trailing-dot prefix (SNS topology style), or `*` wildcard filters."""
        if not patterns:
            return True
        for pattern in patterns:
            if pattern.endswith("*"):
                if event_type.startswith(pattern[:-1]):
                    return True
            elif pattern.endswith("."):
                if event_type.startswith(pattern):
                    return True
            elif event_type == pattern:
                return True
        return False

    async def publish_batch_to_topic(
        self,
        topic_name: str,
        events: Sequence[EventEnvelope],
    ) -> list[str]:
        if not events:
            return []

        now = datetime.now(UTC)
        s = PlatformTopicSubscription
        matched_queues: set[str] = set()

        async with self._session_scope() as session:
            sub_stmt = select(s).where(
                s.topic_name == topic_name,
                s.is_active.is_(True),
            )
            subscriptions = list((await session.execute(sub_stmt)).scalars().all())

            rows_to_insert: list[dict[str, object]] = []
            for sub in subscriptions:
                for event in events:
                    if not self._matches_event_filter(event.event_type, sub.event_types):
                        continue
                    matched_queues.add(sub.target_queue)
                    rows_to_insert.append(self._build_queue_row(sub.target_queue, event, now))

            if rows_to_insert:
                insert_stmt = (
                    pg_insert(PlatformQueueMessage).values(rows_to_insert).on_conflict_do_nothing()
                )
                await session.execute(insert_stmt)
            await session.commit()

        logger.info(
            "database_topic_batch_fanned_out",
            topic_name=topic_name,
            event_count=len(events),
            subscriber_queues=sorted(matched_queues),
            deliveries=len(rows_to_insert),
        )
        return [e.id for e in events]

    async def claim_batch(
        self,
        queue_name: str,
        worker_id: str,
        limit: int = 500,
        lock_lease_ms: int = 30000,
    ) -> list[EventEnvelope]:
        now = datetime.now(UTC)
        lease_until = now + timedelta(milliseconds=lock_lease_ms)
        m = PlatformQueueMessage

        async with self._session_scope() as session:
            pending_ready = (m.status == OutboxStatus.PENDING.value) & or_(
                m.next_retry_at.is_(None),
                m.next_retry_at <= now,
            )
            expired_lease = (m.status == OutboxStatus.PROCESSING.value) & (m.lease_expires_at < now)

            claimed_cte = (
                select(m.id)
                .where(m.queue_name == queue_name)
                .where(or_(pending_ready, expired_lease))
                .order_by(m.lane.desc(), m.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
                .cte("claimed_queue_rows")
            )
            stmt = (
                update(m)
                .where(m.queue_name == queue_name, m.id == claimed_cte.c.id)
                .values(
                    status=OutboxStatus.PROCESSING.value,
                    owner_token=worker_id,
                    lease_expires_at=lease_until,
                    updated_at=now,
                )
                .returning(m)
            )
            res = await session.execute(stmt)
            claimed_rows = list(res.scalars().all())
            await session.commit()

        claimed_rows.sort(
            key=lambda r: (
                0 if r.lane == EventProcessingLane.REALTIME.value else 1,
                r.created_at,
            )
        )
        return [self._to_envelope(row) for row in claimed_rows]

    async def mark_completed_batch(
        self,
        queue_name: str,
        event_ids: Sequence[str],
        worker_id: str,
    ) -> None:
        if not event_ids:
            return
        now = datetime.now(UTC)
        m = PlatformQueueMessage
        async with self._session_scope() as session:
            stmt = (
                update(m)
                .where(
                    m.queue_name == queue_name,
                    m.id.in_(list(event_ids)),
                    m.status == OutboxStatus.PROCESSING.value,
                    m.owner_token == worker_id,
                )
                .values(
                    status=OutboxStatus.PROCESSED.value,
                    published_at=now,
                    updated_at=now,
                    lease_expires_at=None,
                    owner_token=None,
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def mark_failed_batch(
        self,
        queue_name: str,
        event_ids: Sequence[str],
        worker_id: str,
        error_message: str,
        *,
        retry_delay_seconds: int | None = None,
    ) -> None:
        if not event_ids:
            return
        now = datetime.now(UTC)
        m = PlatformQueueMessage
        async with self._session_scope() as session:
            next_status = case(
                (m.attempts + 1 >= m.max_attempts, OutboxStatus.FAILED.value),
                else_=OutboxStatus.PENDING.value,
            )
            if retry_delay_seconds is not None:
                backoff_expr: object = now + timedelta(seconds=max(0, retry_delay_seconds))
            elif self._base_retry_backoff_seconds <= 0:
                backoff_expr = now
            else:
                capped_secs = func.least(
                    self._max_retry_backoff_seconds,
                    self._base_retry_backoff_seconds * func.power(2, m.attempts),
                )
                backoff_expr = func.now() + func.make_interval(0, 0, 0, 0, 0, 0, capped_secs)

            next_retry = case(
                (m.attempts + 1 >= m.max_attempts, None),
                else_=backoff_expr,
            )
            stmt = (
                update(m)
                .where(
                    m.queue_name == queue_name,
                    m.id.in_(list(event_ids)),
                    m.status == OutboxStatus.PROCESSING.value,
                    m.owner_token == worker_id,
                )
                .values(
                    status=next_status,
                    attempts=m.attempts + 1,
                    next_retry_at=next_retry,
                    error_reason=error_message,
                    updated_at=now,
                    lease_expires_at=None,
                    owner_token=None,
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def mark_dead_letter_batch(
        self,
        queue_name: str,
        event_ids: Sequence[str],
        worker_id: str,
        error_message: str,
    ) -> None:
        if not event_ids:
            return
        now = datetime.now(UTC)
        m = PlatformQueueMessage
        async with self._session_scope() as session:
            stmt = (
                update(m)
                .where(
                    m.queue_name == queue_name,
                    m.id.in_(list(event_ids)),
                    m.status == OutboxStatus.PROCESSING.value,
                    m.owner_token == worker_id,
                )
                .values(
                    status=OutboxStatus.FAILED.value,
                    attempts=m.attempts + 1,
                    next_retry_at=None,
                    error_reason=error_message,
                    updated_at=now,
                    lease_expires_at=None,
                    owner_token=None,
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def cleanup_processed(self, retention_days: int = 7) -> int:
        if retention_days < 0:
            raise ValueError("retention_days cannot be negative")
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        total_deleted = 0
        m = PlatformQueueMessage
        while True:
            async with self._session_scope() as session:
                delete_cte = (
                    select(m.queue_name, m.id)
                    .where(
                        m.status.in_((OutboxStatus.PROCESSED.value, OutboxStatus.COMPLETED.value)),
                        m.created_at < cutoff,
                    )
                    .limit(self._CLEANUP_CHUNK_SIZE)
                    .with_for_update(skip_locked=True)
                    .cte("queue_rows_to_delete")
                )
                stmt = (
                    delete(m)
                    .where(
                        tuple_(m.queue_name, m.id).in_(
                            select(delete_cte.c.queue_name, delete_cte.c.id)
                        )
                    )
                    .returning(m.id)
                )
                res = await session.execute(stmt)
                deleted = len(res.scalars().all())
                await session.commit()

            total_deleted += deleted
            if deleted < self._CLEANUP_CHUNK_SIZE:
                break
            await asyncio.sleep(0.1)

        logger.info(
            "database_queue_cleanup_completed",
            retention_days=retention_days,
            deleted_count=total_deleted,
        )
        return total_deleted
