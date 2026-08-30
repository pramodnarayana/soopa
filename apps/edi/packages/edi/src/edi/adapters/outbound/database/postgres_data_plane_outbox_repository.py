import typing
from datetime import UTC, datetime
from typing import Any

import structlog
from seedwork import SystemIdPrefix, generate_id, generate_random_hex
from sqlalchemy import CursorResult, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.events import EventEnvelope
from edi.adapters.outbound.database.constants import DATA_PLANE_OUTBOX_EVENT_PREFIX
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from edi.ports.outbound.data_plane_outbox_repository_port import DataPlaneOutboxRepositoryPort

logger = structlog.get_logger(__name__)

_DELIVERY_LEASE_MINUTES = 5


class SqlAlchemyDataPlaneOutboxRepository(DataPlaneOutboxRepositoryPort):
    """
    Concrete implementation of DataPlaneOutboxRepositoryPort using SQLAlchemy AsyncSession.

    Responsible for all transactional outbox operations: appending events, claiming
    delivery leases, and marking delivery outcomes.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_event(
        self, event_type: str, payload: dict[str, Any], idempotency_key: str | None = None
    ) -> None:
        """Appends a new event to the Data Plane Outbox (idempotent on conflict)."""
        stmt = (
            insert(DataPlaneOutbox)
            .values(
                id=f"{DATA_PLANE_OUTBOX_EVENT_PREFIX}{generate_random_hex(6)}",
                idempotency_key=str(idempotency_key)
                if idempotency_key
                else generate_id(SystemIdPrefix.GENERIC),
                event_type=event_type,
                payload=payload,
                status="PENDING",
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def sweep_stuck_events(self, lock_lease_ms: int = 30000) -> int:
        import asyncio

        total_swept = 0
        while True:
            # We use text-based CTE here to avoid SQLAlchemy ORM issues with SKIP LOCKED inside UPDATE
            from sqlalchemy import text

            query = text("""
                WITH cte AS (
                    SELECT id FROM edi.data_plane_outbox
                    WHERE status = 'PROCESSING'
                      AND updated_at <= NOW() - interval '1 millisecond' * :lock_lease_ms
                    LIMIT 5000
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE edi.data_plane_outbox
                SET status = 'PENDING', lease_expires_at = NULL, owner_token = NULL
                WHERE id IN (SELECT id FROM cte)
            """)
            result = await self._session.execute(query, {"lock_lease_ms": lock_lease_ms})
            swept = int(result.rowcount)  # type: ignore[attr-defined]
            total_swept += swept
            await self._session.flush()
            if swept < 5000:
                break
            await asyncio.sleep(0.1)
        return total_swept

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int = 30000
    ) -> list[EventEnvelope]:
        from sqlalchemy import text

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
        result = await self._session.execute(
            query,
            {
                "worker_id": worker_id,
                "lock_lease_ms": lock_lease_ms,
                "limit": limit,
            },
        )
        await self._session.flush()

        events = []
        for row in result:
            mapping = row._mapping
            events.append(
                EventEnvelope(
                    id=str(mapping["id"]),
                    tenant_id=str(mapping["tenant_id"]) if mapping.get("tenant_id") else None,
                    event_type=str(mapping["event_type"]),
                    payload=typing.cast(dict[str, Any], mapping["payload"]),
                    idempotency_key=mapping.get("idempotency_key"),
                    source="edi_data_plane",
                )
            )
        return events

    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        update_result = await self._session.execute(
            update(DataPlaneOutbox)
            .where(
                DataPlaneOutbox.id == event_id,
                DataPlaneOutbox.status == "PROCESSING",
                DataPlaneOutbox.owner_token == worker_id,
            )
            .values(
                status="PROCESSED",
                owner_token=None,
                lease_expires_at=None,
                updated_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        if typing.cast(CursorResult[Any], update_result).rowcount > 0:
            # Re-fetch the key to insert into processed events if needed, but the ID implies success
            pass
        else:
            logger.warning("stale_success_update", event_id=event_id)

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
        update_result = await self._session.execute(
            update(DataPlaneOutbox)
            .where(
                DataPlaneOutbox.id == event_id,
                DataPlaneOutbox.status == "PROCESSING",
                DataPlaneOutbox.owner_token == worker_id,
            )
            .values(
                status="PENDING",
                attempts=DataPlaneOutbox.attempts + 1,
                lease_expires_at=None,
                owner_token=None,
                updated_at=datetime.now(UTC).replace(tzinfo=None),
                error_reason=error_message,
            )
        )
        if typing.cast(CursorResult[Any], update_result).rowcount == 0:
            logger.warning("stale_failure_update", event_id=event_id)

    async def claim_delivery_outbox_event(self, key_str: str) -> str | None:
        from datetime import UTC, datetime, timedelta

        from seedwork import SystemIdPrefix, generate_id
        from sqlalchemy import or_, update

        owner_token = generate_id(SystemIdPrefix.GENERIC)
        now = datetime.now(UTC).replace(tzinfo=None)
        lease_expires = now + timedelta(minutes=_DELIVERY_LEASE_MINUTES)

        stmt = (
            update(DataPlaneOutbox)
            .where(
                DataPlaneOutbox.idempotency_key == key_str,
                DataPlaneOutbox.status != "PROCESSED",
                or_(
                    DataPlaneOutbox.lease_expires_at.is_(None),
                    DataPlaneOutbox.lease_expires_at < now,
                ),
            )
            .values(
                status="DELIVERING",
                owner_token=owner_token,
                lease_expires_at=lease_expires,
            )
            .returning(DataPlaneOutbox.idempotency_key)
        )
        result = await self._session.execute(stmt)
        if not typing.cast(CursorResult[Any], result).scalar_one_or_none():
            return None
        return owner_token

    async def mark_delivery_success(self, key_str: str, owner_token: str) -> None:
        from sqlalchemy import update
        from sqlalchemy.dialects.postgresql import insert

        from edi.adapters.outbound.database.models.data_plane import ProcessedEvent

        update_result = await self._session.execute(
            update(DataPlaneOutbox)
            .where(
                DataPlaneOutbox.idempotency_key == key_str,
                DataPlaneOutbox.owner_token == owner_token,
            )
            .values(status="PROCESSED", owner_token=None, lease_expires_at=None)
        )
        if typing.cast(CursorResult[Any], update_result).rowcount > 0:
            await self._session.execute(
                insert(ProcessedEvent).values(idempotency_key=key_str).on_conflict_do_nothing()
            )
        else:
            logger.warning("stale_success_update", key_str=key_str)

    async def mark_delivery_failure(self, key_str: str, owner_token: str) -> None:
        from sqlalchemy import update

        result = await self._session.execute(
            update(DataPlaneOutbox)
            .where(
                DataPlaneOutbox.idempotency_key == key_str,
                DataPlaneOutbox.owner_token == owner_token,
            )
            .values(status="FAILED", owner_token=None, lease_expires_at=None)
        )
        if typing.cast(CursorResult[Any], result).rowcount == 0:
            logger.warning("stale_failure_update", key_str=key_str)
