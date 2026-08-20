import typing
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from database.constants import DATA_PLANE_OUTBOX_EVENT_PREFIX
from database.models.data_plane import DataPlaneOutbox, ProcessedEvent
from pipeline.ports.outbox_repository import DataPlaneOutboxRepositoryPort
from sqlalchemy import CursorResult, or_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

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
                id=f"{DATA_PLANE_OUTBOX_EVENT_PREFIX}{uuid.uuid4().hex}",
                idempotency_key=str(idempotency_key) if idempotency_key else str(uuid.uuid4()),
                event_type=event_type,
                payload=payload,
                status="PENDING",
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def claim_delivery_outbox_event(self, key_str: str) -> str | None:
        """
        Atomically claims the outbox event via optimistic locking (CAS).
        Returns the owner_token if the claim succeeds, None if already leased/processed.
        """
        owner_token = str(uuid.uuid4())
        now = datetime.now(UTC)
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
        """
        Marks the outbox event as PROCESSED and inserts a ProcessedEvent for idempotency.
        If the lease was lost (rowcount == 0), a warning is logged and no-op is taken.
        """
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
            logger.warning(
                "Stale success update for key_str={key_str}. Lease was lost.",
                key_str=key_str,
            )

    async def mark_delivery_failure(self, key_str: str, owner_token: str) -> None:
        """
        Marks the outbox event as FAILED, releasing the lease so it can be retried.
        If the lease was lost (rowcount == 0), a warning is logged.
        """
        result = await self._session.execute(
            update(DataPlaneOutbox)
            .where(
                DataPlaneOutbox.idempotency_key == key_str,
                DataPlaneOutbox.owner_token == owner_token,
            )
            .values(status="FAILED", owner_token=None, lease_expires_at=None)
        )
        if typing.cast(CursorResult[Any], result).rowcount == 0:
            logger.warning(
                "Stale failure update for key_str={key_str}. Lease was lost.",
                key_str=key_str,
            )
