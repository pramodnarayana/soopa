from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ucp_models.events import ControlPlaneOutbox


class PostgresOutboxRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def sweep_stuck_events(self, lock_lease_ms: int) -> int:
        async with self.session_factory() as session:
            query = text("""
                UPDATE ucp.outbox
                SET status = 'PENDING', locked_at = NULL, locked_by = NULL
                WHERE status = 'PROCESSING'
                  AND locked_at <= NOW() - interval '1 millisecond' * :lock_lease_ms
            """)
            result = await session.execute(query, {"lock_lease_ms": lock_lease_ms})
            await session.commit()
            return int(result.rowcount)  # type: ignore

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[ControlPlaneOutbox]:
        async with self.session_factory() as session:
            query = text("""
                UPDATE ucp.outbox
                SET status = 'PROCESSING', locked_at = NOW(), locked_by = :worker_id
                WHERE id IN (
                    SELECT id FROM ucp.outbox
                    WHERE (status = 'PENDING' OR (status = 'PROCESSING' AND locked_at < NOW() - interval '1 millisecond' * :lock_lease_ms))
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
                    ControlPlaneOutbox(
                        id=mapping["id"],
                        event_type=mapping["event_type"],
                        payload=mapping["payload"],
                        idempotency_key=mapping.get("idempotency_key"),
                        tenant_id=mapping.get("tenant_id"),
                        status=mapping["status"],
                    )
                )
            return events

    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        async with self.session_factory() as session:
            query = text("""
                UPDATE ucp.outbox
                SET status = 'COMPLETED', locked_at = NULL, locked_by = NULL
                WHERE id = :event_id AND status = 'PROCESSING' AND locked_by = :worker_id
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
        async with self.session_factory() as session:
            query = text("""
                UPDATE ucp.outbox
                SET status = 'FAILED', locked_at = NULL, locked_by = NULL, error_message = :error_message
                WHERE id = :event_id AND status = 'PROCESSING' AND locked_by = :worker_id
            """)
            await session.execute(
                query,
                {
                    "event_id": event_id,
                    "worker_id": worker_id,
                    "error_message": error_message,
                },
            )
            await session.commit()
