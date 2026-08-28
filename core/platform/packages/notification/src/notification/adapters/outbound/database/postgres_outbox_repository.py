from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import structlog
from database.events import EventEnvelope
from database.models.notifications import NotificationOutbox
from outbox.domain.constants import OutboxStatus
from sqlalchemy import case, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ....ports.outbound.notification_outbox_repository_port import NotificationOutboxRepositoryPort

logger = structlog.get_logger(__name__)


class SqlAlchemyNotificationOutboxRepository(NotificationOutboxRepositoryPort):
    def __init__(self, session_factory: Callable[[], AsyncSession]):
        self.session_factory = session_factory

    async def save(self, message: EventEnvelope) -> None:
        import os

        async with self.session_factory() as session, session.begin():
            orm_msg = NotificationOutbox(
                id=message.id or f"{NotificationOutbox.ID_PREFIX}_{os.urandom(12).hex()}",
                tenant_id=message.tenant_id,
                event_type=message.event_type,
                idempotency_key=message.idempotency_key,
                payload=message.payload,
            )
            session.add(orm_msg)

    async def sweep_stuck_events(self, lock_lease_ms: int) -> int:
        import asyncio

        total_swept = 0
        threshold = datetime.now(UTC) - timedelta(milliseconds=lock_lease_ms)

        async with self.session_factory() as session:
            while True:
                stmt = (
                    update(NotificationOutbox)
                    .where(
                        NotificationOutbox.id.in_(
                            select(NotificationOutbox.id)
                            .where(
                                NotificationOutbox.status == OutboxStatus.PROCESSING.value,
                                NotificationOutbox.updated_at < threshold,
                            )
                            .limit(500)
                        ),
                        NotificationOutbox.status == OutboxStatus.PROCESSING.value,
                        NotificationOutbox.updated_at < threshold,
                    )
                    .values(status=OutboxStatus.PENDING.value, owner_token=None)
                )
                result = await session.execute(stmt)
                swept = cast(CursorResult[Any], result).rowcount
                total_swept += swept
                await session.commit()

                if swept < 500:
                    break

                await asyncio.sleep(0.1)

        return total_swept

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[EventEnvelope]:
        async with self.session_factory() as session, session.begin():
            # 1. Select for update skip locked
            stmt = (
                select(NotificationOutbox.id)
                .where(NotificationOutbox.status == OutboxStatus.PENDING.value)
                .order_by(NotificationOutbox.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            message_ids = [row[0] for row in result.all()]

            if not message_ids:
                return []

            # 2. Update to processing
            now = datetime.now(UTC)
            update_stmt = (
                update(NotificationOutbox)
                .where(NotificationOutbox.id.in_(message_ids))
                .values(
                    status=OutboxStatus.PROCESSING.value,
                    owner_token=worker_id,
                    updated_at=now,
                    lease_expires_at=now + timedelta(milliseconds=lock_lease_ms),
                )
                .returning(NotificationOutbox)
            )
            updated = await session.execute(update_stmt)
            orm_messages = list(updated.scalars().all())

            return [
                EventEnvelope(
                    id=msg.id,
                    source="notification",
                    tenant_id=msg.tenant_id,
                    event_type=msg.event_type,
                    idempotency_key=msg.idempotency_key,
                    payload=msg.payload,
                )
                for msg in orm_messages
            ]

    async def mark_completed(self, message_id: str, worker_id: str) -> None:
        async with self.session_factory() as session, session.begin():
            stmt = (
                update(NotificationOutbox)
                .where(
                    NotificationOutbox.id == message_id,
                    NotificationOutbox.owner_token == worker_id,
                )
                .values(status=OutboxStatus.PROCESSED.value, updated_at=datetime.now(UTC))
            )
            result = await session.execute(stmt)
            if cast(CursorResult[Any], result).rowcount == 0:
                logger.warning(
                    "Lost lease on message {message_id} (worker {worker_id}) - no rows updated in mark_completed",
                    message_id=message_id,
                    worker_id=worker_id,
                )

    async def mark_failed(self, message_id: str, worker_id: str, error_reason: str) -> None:
        async with self.session_factory() as session, session.begin():
            stmt = (
                update(NotificationOutbox)
                .where(
                    NotificationOutbox.id == message_id,
                    NotificationOutbox.owner_token == worker_id,
                )
                .values(
                    status=case(
                        (NotificationOutbox.attempts + 1 >= 3, OutboxStatus.FAILED.value),
                        else_=OutboxStatus.PENDING.value,
                    ),
                    attempts=NotificationOutbox.attempts + 1,
                    owner_token=None,
                    lease_expires_at=None,
                    error_reason=error_reason[:1000],
                    updated_at=datetime.now(UTC),
                )
            )
            result = await session.execute(stmt)
            if cast(CursorResult[Any], result).rowcount == 0:
                logger.warning(
                    "Lost lease on message {message_id} (worker {worker_id}) - no rows updated in mark_failed",
                    message_id=message_id,
                    worker_id=worker_id,
                )


class SqlAlchemyNotificationOutboxPublisher:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, message: EventEnvelope) -> None:
        import os

        orm_msg = NotificationOutbox(
            id=message.id or f"{NotificationOutbox.ID_PREFIX}_{os.urandom(12).hex()}",
            tenant_id=message.tenant_id,
            event_type=message.event_type,
            idempotency_key=message.idempotency_key,
            payload=message.payload,
        )
        self.session.add(orm_msg)
