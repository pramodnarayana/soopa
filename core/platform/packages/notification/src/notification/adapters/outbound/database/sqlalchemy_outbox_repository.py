"""SQLAlchemy ORM adapter for staging transactional Notification outbox events."""

from __future__ import annotations

import structlog
from database.models.notifications import NotificationOutbox
from database.outbox_serializer import map_outbox_row_to_envelope
from seedwork.events import EventEnvelope
from seedwork.utils import generate_id
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from notification.domain.constants import NotificationOutboxSource
from notification.ports.outbound.notification_outbox_repository_port import (
    NotificationOutboxRepositoryPort,
)

logger = structlog.get_logger(__name__)


class SqlAlchemyNotificationOutboxRepository(NotificationOutboxRepositoryPort):
    """Stages notification outbox envelopes within the caller's UoW transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _to_orm_record(message: EventEnvelope) -> NotificationOutbox:
        return NotificationOutbox(
            id=message.id or generate_id(NotificationOutbox.ID_PREFIX),
            tenant_id=message.tenant_id or "",
            event_type=message.event_type,
            idempotency_key=message.idempotency_key or generate_id(NotificationOutbox.ID_PREFIX),
            payload=message.payload,
            trace_id=message.trace_id,
            correlation_id=message.correlation_id,
            lane=message.lane.value,
        )

    @staticmethod
    def _to_domain_model(record: NotificationOutbox) -> EventEnvelope:
        return map_outbox_row_to_envelope(
            record,
            source=NotificationOutboxSource.NOTIFICATION.value,
        )

    async def save(self, message: EventEnvelope) -> None:
        record = self._to_orm_record(message)
        stmt = (
            pg_insert(NotificationOutbox)
            .values(
                id=record.id,
                tenant_id=record.tenant_id,
                event_type=record.event_type,
                idempotency_key=record.idempotency_key,
                payload=record.payload,
                trace_id=record.trace_id,
                correlation_id=record.correlation_id,
                lane=record.lane,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(NotificationOutbox.id)
        )
        inserted_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if inserted_id is None:
            logger.info(
                "notification_outbox_duplicate_skipped",
                tenant_id=record.tenant_id,
                event_type=record.event_type,
                idempotency_key=record.idempotency_key,
            )


__all__ = ["SqlAlchemyNotificationOutboxRepository"]
