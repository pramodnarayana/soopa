import asyncio
from typing import Any, cast

from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from platform_orm.events import EventEnvelope
from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class PostgresIdentityOutboxRepository(OutboxRepositoryPort):
    """
    Infrastructure adapter for the Identity outbox table.
    Implements the outbox port for the identity.outbox schema.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def sweep_stuck_events(self, lock_lease_ms: int) -> int:
        total_swept = 0
        async with self.session_factory() as session:
            while True:
                query = text("""
                    WITH cte AS (
                        SELECT id FROM identity.outbox
                        WHERE status = 'PROCESSING'
                          AND updated_at <= NOW() - interval '1 millisecond' * :lock_lease_ms
                        LIMIT 5000
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE identity.outbox
                    SET status = 'PENDING', lease_expires_at = NULL, owner_token = NULL
                    WHERE id IN (SELECT id FROM cte)
                """)
                result = cast(
                    CursorResult[Any],
                    await session.execute(query, {"lock_lease_ms": lock_lease_ms}),
                )
                swept = int(result.rowcount)
                total_swept += swept
                await session.commit()
                if swept < 5000:
                    break
                await asyncio.sleep(0.1)
        return total_swept

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[EventEnvelope]:
        async with self.session_factory() as session:
            query = text("""
                UPDATE identity.outbox
                SET status = 'PROCESSING', updated_at = NOW(),
                    lease_expires_at = NOW() + interval '1 millisecond' * :lock_lease_ms,
                    owner_token = :worker_id
                WHERE id IN (
                    SELECT id FROM identity.outbox
                    WHERE (status = 'PENDING' OR (status = 'PROCESSING' AND lease_expires_at < NOW()))
                    ORDER BY created_at ASC
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *;
            """)
            result = await session.execute(
                query,
                {
                    "worker_id": worker_id,
                    "lock_lease_ms": lock_lease_ms,
                    "limit": limit,
                },
            )
            await session.commit()

            events = []
            for row in result:
                mapping = row._mapping
                events.append(
                    EventEnvelope(
                        id=mapping["id"],
                        source="soopa.identity",
                        event_type=mapping["event_type"],
                        payload=mapping["payload"],
                        idempotency_key=mapping.get("idempotency_key"),
                        tenant_id=mapping.get("tenant_id"),
                    )
                )
            return events

    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        async with self.session_factory() as session:
            query = text("""
                UPDATE identity.outbox
                SET status = 'COMPLETED', lease_expires_at = NULL, owner_token = NULL, updated_at = NOW()
                WHERE id = :event_id AND status = 'PROCESSING' AND owner_token = :worker_id
            """)
            await session.execute(query, {"event_id": event_id, "worker_id": worker_id})
            await session.commit()

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
        async with self.session_factory() as session:
            query = text("""
                UPDATE identity.outbox
                SET status = CASE WHEN attempts + 1 >= :max_attempts THEN 'FAILED' ELSE 'PENDING' END,
                    attempts = attempts + 1, lease_expires_at = NULL, owner_token = NULL,
                    updated_at = NOW(), error_reason = :error_message
                WHERE id = :event_id AND status = 'PROCESSING' AND owner_token = :worker_id
            """)
            await session.execute(
                query,
                {
                    "event_id": event_id,
                    "worker_id": worker_id,
                    "error_message": error_message,
                    "max_attempts": 3,
                },
            )
            await session.commit()
