import asyncio
from collections.abc import Sequence
from typing import Any, cast

import structlog
from database.router import DatabaseRouterPort
from outbox.domain.constants import OutboxStatus
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from seedwork.events import EventEnvelope
from sqlalchemy import CursorResult, text

logger = structlog.get_logger(__name__)


class SqlAlchemyEdiDataPlaneOutboxSweeperRepository(OutboxRepositoryPort):
    """
    SQLAlchemy implementation for sweeping stranded outbox events across tenant shards.
    """

    def __init__(self, db_router: DatabaseRouterPort, app_slug: str = "edi") -> None:
        self.db_router = db_router
        self.app_slug = app_slug

    async def sweep_stuck_events(self, lock_lease_ms: int = 30000) -> int:
        total_swept = 0
        try:
            shards = await self.db_router.get_all_shards(app_slug=self.app_slug)
            for shard_name, shard_dsn in shards:
                async for session in self.db_router.get_shard_session(shard_name, shard_dsn):
                    while True:
                        query = text("""
                            WITH cte AS (
                                SELECT id FROM outbox
                                WHERE status = :status_processing
                                  AND lease_expires_at < NOW()
                                LIMIT 5000
                                FOR UPDATE SKIP LOCKED
                            )
                            UPDATE outbox
                            SET status = :status_pending, lease_expires_at = NULL, owner_token = NULL
                            WHERE id IN (SELECT id FROM cte)
                        """)
                        result = cast(
                            CursorResult[Any],
                            await session.execute(
                                query,
                                {
                                    "status_processing": OutboxStatus.PROCESSING.value,
                                    "status_pending": OutboxStatus.PENDING.value,
                                },
                            ),
                        )
                        swept = int(result.rowcount)
                        total_swept += swept
                        await session.commit()
                        if swept < 5000:
                            break
                        await asyncio.sleep(0.1)
        except Exception:
            logger.exception("failed_to_sweep_data_plane_outbox_events")
            raise

        return total_swept

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int = 30000
    ) -> list[EventEnvelope]:
        events: list[EventEnvelope] = []
        try:
            shards = await self.db_router.get_all_shards(app_slug=self.app_slug)
            for shard_name, shard_dsn in shards:
                if len(events) >= limit:
                    break
                async for session in self.db_router.get_shard_session(shard_name, shard_dsn):
                    query = text("""
                        UPDATE outbox
                        SET status = :status_processing, updated_at = NOW(),
                            lease_expires_at = NOW() + interval '1 millisecond' * :lock_lease_ms,
                            owner_token = :worker_id
                        WHERE id IN (
                            SELECT id FROM outbox
                            WHERE ((status = :status_pending AND created_at < NOW() - interval '60 seconds') OR (status = :status_processing AND lease_expires_at < NOW()))
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
                            "limit": limit - len(events),
                            "status_processing": OutboxStatus.PROCESSING.value,
                            "status_pending": OutboxStatus.PENDING.value,
                        },
                    )
                    await session.commit()

                    for row in result:
                        mapping = row._mapping
                        events.append(
                            EventEnvelope(
                                id=mapping["id"],
                                source="edi",
                                event_type=mapping["event_type"],
                                payload=mapping["payload"],
                                idempotency_key=mapping.get("idempotency_key"),
                                tenant_id=mapping.get("tenant_id"),
                            )
                        )
        except Exception:
            logger.exception("failed_to_claim_data_plane_outbox_events")
            raise
        return events

    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        await self.mark_completed_batch([event_id], worker_id)

    async def mark_completed_batch(self, event_ids: Sequence[str], worker_id: str) -> None:
        if not event_ids:
            return
        try:
            shards = await self.db_router.get_all_shards(app_slug=self.app_slug)
            remaining_ids = set(event_ids)
            for shard_name, shard_dsn in shards:
                if not remaining_ids:
                    break
                async for session in self.db_router.get_shard_session(shard_name, shard_dsn):
                    query = text("""
                        UPDATE outbox
                        SET status = :status_processed, lease_expires_at = NULL, owner_token = NULL, updated_at = NOW()
                        WHERE id = ANY(:event_ids) AND status = :status_processing AND owner_token = :worker_id
                        RETURNING id
                    """)
                    res = await session.execute(
                        query,
                        {
                            "event_ids": list(remaining_ids),
                            "status_processing": OutboxStatus.PROCESSING.value,
                            "status_processed": OutboxStatus.PROCESSED.value,
                            "worker_id": worker_id,
                        },
                    )
                    await session.commit()
                    updated = set(res.scalars().all())
                    remaining_ids -= updated
        except Exception:
            logger.exception("failed_to_mark_completed_data_plane_outbox")
            raise

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
        await self.mark_failed_batch([event_id], worker_id, error_message)

    async def mark_failed_batch(
        self, event_ids: Sequence[str], worker_id: str, error_message: str
    ) -> None:
        if not event_ids:
            return
        try:
            shards = await self.db_router.get_all_shards(app_slug=self.app_slug)
            remaining_ids = set(event_ids)
            for shard_name, shard_dsn in shards:
                if not remaining_ids:
                    break
                async for session in self.db_router.get_shard_session(shard_name, shard_dsn):
                    query = text("""
                        UPDATE outbox
                        SET status = :status_failed, lease_expires_at = NULL, owner_token = NULL, updated_at = NOW(), error_reason = :error_message
                        WHERE id = ANY(:event_ids) AND status = :status_processing AND owner_token = :worker_id
                        RETURNING id
                    """)
                    res = await session.execute(
                        query,
                        {
                            "event_ids": list(remaining_ids),
                            "error_message": error_message,
                            "status_processing": OutboxStatus.PROCESSING.value,
                            "status_failed": OutboxStatus.FAILED.value,
                            "worker_id": worker_id,
                        },
                    )
                    await session.commit()
                    updated = set(res.scalars().all())
                    remaining_ids -= updated
        except Exception:
            logger.exception("failed_to_mark_failed_data_plane_outbox")
            raise
