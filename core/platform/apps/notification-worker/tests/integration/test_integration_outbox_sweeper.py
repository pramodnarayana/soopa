from collections.abc import Sequence

import pytest
from database.models.identity import Tenant
from database.models.notifications import NotificationOutbox
from notification.adapters.outbound.database.sqlalchemy_outbox_repository import (
    SqlAlchemyNotificationOutboxRepository,
)
from notification.domain.constants import NotificationOutboxSource
from outbox.adapters.outbound.sqlalchemy_global_outbox_repository import (
    SqlAlchemyGlobalOutboxRepository,
)
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from outbox.domain.constants import OutboxStatus
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class FakeDispatcher:
    def __init__(self) -> None:
        self.dispatches: list[JsonDict] = []

    async def publish_batch(self, events: Sequence[EventEnvelope]) -> Sequence[str]:
        successful_ids: list[str] = []
        for event in events:
            self.dispatches.append(
                {
                    "event_type": event.event_type,
                    "tenant_id": event.tenant_id,
                    "payload": event.payload,
                }
            )
            successful_ids.append(event.id)
        return successful_ids


async def test_outbox_sweeper_integration(db_session_factory) -> None:
    """
    A High-Quality Narrow Integration Test that uses a real Postgres database
    to verify that the Outbox Sweeper successfully claims messages from the DB,
    processes them, and marks them as completed.
    """
    repo = SqlAlchemyGlobalOutboxRepository(
        session_factory=db_session_factory,
        model_cls=NotificationOutbox,
        source=NotificationOutboxSource.NOTIFICATION.value,
    )
    dispatcher = FakeDispatcher()

    message = EventEnvelope(
        id="msg-123",
        source=NotificationOutboxSource.NOTIFICATION.value,
        event_type="invoice.paid",
        idempotency_key="idemp-123",
        tenant_id="t1",
        payload={
            "channel": "EMAIL",
            "content": "Your invoice is paid",
            "subject": "Paid!",
            "data": {"id": "123"},
        },
    )

    async with db_session_factory() as session, session.begin():
        stmt = (
            insert(Tenant).values(id="t1", name="Test Tenant", slug="t1").on_conflict_do_nothing()
        )
        await session.execute(stmt)
        outbox_writer = SqlAlchemyNotificationOutboxRepository(session)
        await outbox_writer.save(message)

    processor = OutboxSweeperUseCase(repository=repo, publisher=dispatcher)

    # 2. Run a single poll cycle
    await processor.execute()

    # 3. Verify it was dispatched
    assert len(dispatcher.dispatches) == 1
    dispatched_payload = dispatcher.dispatches[0]["payload"]
    assert isinstance(dispatched_payload, dict)
    assert dispatched_payload["channel"] == "EMAIL"
    assert dispatcher.dispatches[0]["tenant_id"] == "t1"

    # 4. Verify it was marked as PROCESSED in the database with lease released
    async with db_session_factory() as session:
        select_stmt = select(NotificationOutbox).where(NotificationOutbox.tenant_id == "t1")
        result = await session.execute(select_stmt)
        outbox_row = result.scalars().first()

        assert outbox_row is not None
        assert outbox_row.status == OutboxStatus.PROCESSED.value
        assert outbox_row.published_at is not None
        assert outbox_row.owner_token is None
