import asyncio
from typing import Any, cast

import structlog
from database.events import EventEnvelope
from edi.adapters.outbound.database.connection import DatabaseRouter
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from sqlalchemy import CursorResult, TextClause, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class PostgresEdiDataPlaneOutboxRepository(OutboxRepositoryPort):
    def __init__(self, db_router: DatabaseRouter) -> None:
        self.db_router = db_router

    async def _claim_from_shard(
        self,
        shard_name: str,
        shard_dsn: str,
        worker_id: str,
        limit: int,
        lock_lease_ms: int,
    ) -> list[EventEnvelope]:
        if limit <= 0:
            return []

        engine = await self.db_router.get_engine(shard_name, shard_dsn)
        async with AsyncSession(engine, expire_on_commit=False) as session:
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

            return [
                EventEnvelope(
                    id=str(row._mapping["id"]),
                    tenant_id=(
                        str(row._mapping["tenant_id"]) if row._mapping.get("tenant_id") else None
                    ),
                    event_type=str(row._mapping["event_type"]),
                    payload=cast(dict[str, Any], row._mapping["payload"]),
                    idempotency_key=row._mapping.get("idempotency_key"),
                    source="edi_data_plane",
                )
                for row in result
            ]

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int = 30000
    ) -> list[EventEnvelope]:
        if limit <= 0:
            return []

        shards = await self.db_router.get_all_shards()
        if not shards:
            return []

        # Give every shard an initial share so a busy first shard cannot starve the rest.
        quota = max(1, limit // len(shards))
        events: list[EventEnvelope] = []
        for shard_name, shard_dsn in shards:
            events.extend(
                await self._claim_from_shard(
                    shard_name,
                    shard_dsn,
                    worker_id,
                    min(quota, limit - len(events)),
                    lock_lease_ms,
                )
            )

        # Reuse spare capacity when one of the initial shard allocations was empty.
        for shard_name, shard_dsn in shards:
            remaining = limit - len(events)
            if remaining <= 0:
                break
            events.extend(
                await self._claim_from_shard(
                    shard_name, shard_dsn, worker_id, remaining, lock_lease_ms
                )
            )

        return events

    async def sweep_stuck_events(self, lock_lease_ms: int = 30000) -> int:
        del lock_lease_ms  # Lease expiry is persisted per row and compared to the database clock.
        total_swept = 0
        for shard_name, shard_dsn in await self.db_router.get_all_shards():
            engine = await self.db_router.get_engine(shard_name, shard_dsn)
            async with AsyncSession(engine, expire_on_commit=False) as session:
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
                    result = cast(CursorResult[Any], await session.execute(query))
                    swept = int(result.rowcount)
                    total_swept += swept
                    await session.commit()
                    if swept < 5000:
                        break
                    await asyncio.sleep(0.1)
        return total_swept

    async def _update_all_shards(self, query: TextClause, params: dict[str, Any]) -> None:
        async def _update(shard_name: str, shard_dsn: str) -> None:
            engine = await self.db_router.get_engine(shard_name, shard_dsn)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await session.execute(query, params)
                await session.commit()

        results = await asyncio.gather(
            *[
                _update(shard_name, shard_dsn)
                for shard_name, shard_dsn in await self.db_router.get_all_shards()
            ],
            return_exceptions=True,
        )
        exceptions = [result for result in results if isinstance(result, Exception)]
        if exceptions:
            raise ExceptionGroup("tenant_shard_outbox_update_failed", exceptions)

    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        await self._update_all_shards(
            text("""
                UPDATE edi.data_plane_outbox
                SET status = 'PROCESSED', lease_expires_at = NULL, owner_token = NULL, updated_at = NOW()
                WHERE id = :event_id AND status = 'PROCESSING' AND owner_token = :worker_id
            """),
            {"event_id": event_id, "worker_id": worker_id},
        )

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
        await self._update_all_shards(
            text("""
                UPDATE edi.data_plane_outbox
                SET status = CASE WHEN attempts + 1 >= :max_attempts THEN 'FAILED' ELSE 'PENDING' END,
                    attempts = attempts + 1,
                    lease_expires_at = NULL,
                    owner_token = NULL,
                    updated_at = NOW(),
                    error_reason = :error_message
                WHERE id = :event_id AND status = 'PROCESSING' AND owner_token = :worker_id
            """),
            {
                "event_id": event_id,
                "worker_id": worker_id,
                "error_message": error_message,
                "max_attempts": 3,
            },
        )
