from contextlib import asynccontextmanager
from typing import Any, cast

import structlog
from edi.adapters.outbound.database.connection import DatabaseRouter
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from platform_orm.events import EventEnvelope
from sqlalchemy import CursorResult, text

logger = structlog.get_logger(__name__)


class PostgresEdiDataPlaneOutboxRepository(OutboxRepositoryPort):
    def __init__(self, db_router: DatabaseRouter):
        self.db_router = db_router

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int = 30000
    ) -> list[EventEnvelope]:
        async with asynccontextmanager(self.db_router.get_global_session)() as session:
            query = text("""
                UPDATE edi.data_plane_outbox
                SET status = 'PROCESSING', updated_at = NOW(), lease_expires_at = NOW() + interval '1 millisecond' * :lock_lease_ms, owner_token = :worker_id
                WHERE id IN (
                    SELECT id FROM edi.data_plane_outbox
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
                        id=str(mapping["id"]),
                        tenant_id=str(mapping["tenant_id"]) if mapping.get("tenant_id") else None,
                        event_type=str(mapping["event_type"]),
                        payload=cast(dict[str, Any], mapping["payload"]),
                        idempotency_key=mapping.get("idempotency_key"),
                        source="edi_data_plane",
                    )
                )
            return events

    async def sweep_stuck_events(self, lock_lease_ms: int = 30000) -> int:
        import asyncio

        total_swept = 0
        async with asynccontextmanager(self.db_router.get_global_session)() as session:
            while True:
                query = text("""
                    WITH cte AS (
                        SELECT id FROM edi.data_plane_outbox
                        WHERE status = 'PROCESSING'
                          AND lease_expires_at < NOW()
                        LIMIT 5000
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE edi.data_plane_outbox
                    SET status = 'PENDING', lease_expires_at = NULL, owner_token = NULL
                    WHERE id IN (SELECT id FROM cte)
                """)
                result = cast(
                    CursorResult[Any],
                    await session.execute(query),
                )
                swept = int(result.rowcount)
                total_swept += swept
                await session.commit()
                if swept < 5000:
                    break
                await asyncio.sleep(0.1)
        return total_swept

    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        async with asynccontextmanager(self.db_router.get_global_session)() as session:
            query = text("""
                UPDATE edi.data_plane_outbox
                SET status = 'PROCESSED', lease_expires_at = NULL, owner_token = NULL, updated_at = NOW()
                WHERE id = :event_id AND status = 'PROCESSING' AND owner_token = :worker_id
            """)
            await session.execute(
                query,
                {
                    "event_id": event_id,
                    "worker_id": worker_id,
                },
            )
            await session.commit()

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
        async with asynccontextmanager(self.db_router.get_global_session)() as session:
            query = text("""
                UPDATE edi.data_plane_outbox
                SET status = CASE WHEN attempts + 1 >= :max_attempts THEN 'FAILED' ELSE 'PENDING' END,
                    attempts = attempts + 1,
                    lease_expires_at = NULL,
                    owner_token = NULL,
                    updated_at = NOW(),
                    error_reason = :error_message
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
