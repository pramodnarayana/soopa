from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.notifications import NotificationOutbox

from ...ports.outbox_repository import NotificationOutboxRepositoryPort


class PostgresOutboxRepository(NotificationOutboxRepositoryPort):
    def __init__(self, session_factory: Callable[[], AsyncSession]):
        self.session_factory = session_factory

    async def save(self, message: NotificationOutbox) -> None:
        async with self.session_factory() as session, session.begin():
            session.add(message)

    async def sweep_stuck_messages(self, lock_lease_ms: int) -> int:
        async with self.session_factory() as session, session.begin():
            threshold = datetime.now(UTC) - timedelta(milliseconds=lock_lease_ms)
            stmt = (
                update(NotificationOutbox)
                .where(
                    NotificationOutbox.status == "PROCESSING",
                    NotificationOutbox.updated_at < threshold.replace(tzinfo=None),
                )
                .values(status="PENDING", owner_token=None)
            )
            result = await session.execute(stmt)
            return cast(CursorResult[Any], result).rowcount

    async def claim_next_messages(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[NotificationOutbox]:
        async with self.session_factory() as session, session.begin():
            # 1. Select for update skip locked
            stmt = (
                select(NotificationOutbox.id)
                .where(NotificationOutbox.status == "PENDING")
                .order_by(NotificationOutbox.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            message_ids = [row[0] for row in result.all()]

            if not message_ids:
                return []

            # 2. Update to processing
            now = datetime.now(UTC).replace(tzinfo=None)
            update_stmt = (
                update(NotificationOutbox)
                .where(NotificationOutbox.id.in_(message_ids))
                .values(
                    status="PROCESSING",
                    owner_token=worker_id,
                    updated_at=now,
                    lease_expires_at=now + timedelta(milliseconds=lock_lease_ms),
                )
                .returning(NotificationOutbox)
            )
            updated = await session.execute(update_stmt)
            return list(updated.scalars().all())

    async def mark_completed(self, message_id: str, worker_id: str) -> None:
        async with self.session_factory() as session, session.begin():
            stmt = (
                update(NotificationOutbox)
                .where(
                    NotificationOutbox.id == message_id,
                    NotificationOutbox.owner_token == worker_id,
                )
                .values(status="COMPLETED", updated_at=datetime.now(UTC).replace(tzinfo=None))
            )
            await session.execute(stmt)

    async def mark_failed(self, message_id: str, worker_id: str, error_reason: str) -> None:
        async with self.session_factory() as session, session.begin():
            stmt = (
                update(NotificationOutbox)
                .where(
                    NotificationOutbox.id == message_id,
                    NotificationOutbox.owner_token == worker_id,
                )
                .values(
                    status="FAILED",
                    error_reason=error_reason[:1000],
                    updated_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            await session.execute(stmt)
