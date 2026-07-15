import uuid
from typing import Any
from uuid import UUID

from api.ports.outbox_repository import OutboxRepositoryPort
from database.base_repository import BaseSqlAlchemyRepository
from database.models.control_plane import Outbox as GlobalOutbox
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyOutboxRepository(OutboxRepositoryPort, BaseSqlAlchemyRepository):
    def __init__(self, session: AsyncSession, model_class: Any = GlobalOutbox) -> None:
        self.session = session
        self.model_class = model_class

    async def publish_outbox_event(
        self, tenant_id: int, event_type: str, payload: dict[str, Any]
    ) -> UUID:
        event_id = uuid.uuid4()
        record = self.model_class(
            id=event_id,
            tenant_id=tenant_id,
            idempotency_key=uuid.uuid4(),
            event_type=event_type,
            payload=payload,
            status="PENDING",
        )
        self.session.add(record)
        await self.session.flush()
        return event_id
