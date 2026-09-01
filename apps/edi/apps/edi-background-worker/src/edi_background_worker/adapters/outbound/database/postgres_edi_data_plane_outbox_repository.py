import asyncio
from typing import Any

import structlog
from database.events import EventEnvelope
from database.router import DatabaseRouter
from outbox.domain.constants import OutboxStatus
from outbox.ports.outbox_repository_port import OutboxRepositoryPort

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

        async for session in self.db_router.get_shard_session(shard_name, shard_dsn):
            from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
            from sqlalchemy import and_, func, or_, select, text, update

            subq = (
                select(DataPlaneOutbox.id)
                .where(
                    or_(
                        DataPlaneOutbox.status == OutboxStatus.PENDING.value,
                        and_(
                            DataPlaneOutbox.status == OutboxStatus.PROCESSING.value,
                            DataPlaneOutbox.lease_expires_at < func.now(),
                        ),
                    )
                )
                .order_by(DataPlaneOutbox.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
                .scalar_subquery()
            )

            stmt = (
                update(DataPlaneOutbox)
                .where(DataPlaneOutbox.id.in_(subq))
                .values(
                    status=OutboxStatus.PROCESSING.value,
                    updated_at=func.now(),
                    lease_expires_at=func.now()
                    + text(f"interval '1 millisecond' * {int(lock_lease_ms)}"),
                    owner_token=worker_id,
                )
                .returning(DataPlaneOutbox)
            )

            result = await session.execute(stmt)
            await session.commit()

            return [
                EventEnvelope(
                    id=str(row.id),
                    tenant_id=str(row.tenant_id) if row.tenant_id else None,
                    event_type=str(row.event_type),
                    payload=row.payload,
                    idempotency_key=row.idempotency_key,
                    source="edi_data_plane",
                )
                for row in result.scalars()
            ]

        return []

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
            async for session in self.db_router.get_shard_session(shard_name, shard_dsn):
                from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
                from sqlalchemy import and_, func, select, update

                while True:
                    subq = (
                        select(DataPlaneOutbox.id)
                        .where(
                            and_(
                                DataPlaneOutbox.status == OutboxStatus.PROCESSING.value,
                                DataPlaneOutbox.lease_expires_at < func.now(),
                            )
                        )
                        .limit(5000)
                        .with_for_update(skip_locked=True)
                        .scalar_subquery()
                    )

                    stmt = (
                        update(DataPlaneOutbox)
                        .where(DataPlaneOutbox.id.in_(subq))
                        .values(
                            status=OutboxStatus.PENDING.value,
                            lease_expires_at=None,
                            owner_token=None,
                        )
                    )

                    result = await session.execute(stmt)
                    swept = int(getattr(result, "rowcount", 0))
                    total_swept += swept
                    await session.commit()
                    if swept < 5000:
                        break
                    await asyncio.sleep(0.1)
        return total_swept

    async def _update_all_shards(self, get_stmt: Any, params: dict[str, Any]) -> None:
        async def _update(shard_name: str, shard_dsn: str) -> None:
            async for session in self.db_router.get_shard_session(shard_name, shard_dsn):
                await session.execute(get_stmt(params))
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
        from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
        from sqlalchemy import and_, func, update

        def _get_stmt(params: dict[str, Any]) -> Any:
            return (
                update(DataPlaneOutbox)
                .where(
                    and_(
                        DataPlaneOutbox.id == params["event_id"],
                        DataPlaneOutbox.status == OutboxStatus.PROCESSING.value,
                        DataPlaneOutbox.owner_token == params["worker_id"],
                    )
                )
                .values(
                    status=OutboxStatus.PROCESSED.value,
                    lease_expires_at=None,
                    owner_token=None,
                    updated_at=func.now(),
                )
            )

        await self._update_all_shards(
            _get_stmt,
            {"event_id": event_id, "worker_id": worker_id},
        )

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
        from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
        from sqlalchemy import and_, case, func, update

        def _get_stmt(params: dict[str, Any]) -> Any:
            return (
                update(DataPlaneOutbox)
                .where(
                    and_(
                        DataPlaneOutbox.id == params["event_id"],
                        DataPlaneOutbox.status == OutboxStatus.PROCESSING.value,
                        DataPlaneOutbox.owner_token == params["worker_id"],
                    )
                )
                .values(
                    status=case(
                        (
                            DataPlaneOutbox.attempts + 1 >= params["max_attempts"],
                            OutboxStatus.FAILED.value,
                        ),
                        else_=OutboxStatus.PENDING.value,
                    ),
                    attempts=DataPlaneOutbox.attempts + 1,
                    lease_expires_at=None,
                    owner_token=None,
                    updated_at=func.now(),
                    error_reason=params["error_message"],
                )
            )

        await self._update_all_shards(
            _get_stmt,
            {
                "event_id": event_id,
                "worker_id": worker_id,
                "error_message": error_message,
                "max_attempts": 3,
            },
        )
