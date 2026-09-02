from collections.abc import Sequence
from typing import Any

import pytest
from database.models.identity import Tenant
from database.models.notifications import NotificationOutbox
from notification.adapters.outbound.database.postgres_outbox_repository import (
    SqlAlchemyNotificationOutboxRepository,
)
from notification.domain.models import NotificationOutboxEvent
from outbox.application.outbox_sweeper_use_case import (
    OutboxSweeperUseCase,
)
from outbox.domain.constants import OutboxStatus
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert


class FakeDispatcher:
    def __init__(self):
        self.dispatches = []

    async def publish_batch(self, events: Sequence[Any]) -> Sequence[str]:
        successful_ids = []
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


@pytest.mark.asyncio
async def test_outbox_sweeper_integration(db_session_factory):
    """
    A High-Quality Narrow Integration Test that uses a real Postgres database
    to verify that the Outbox Sweeper successfully claims messages from the DB,
    processes them, and marks them as completed.
    """
    repo = SqlAlchemyNotificationOutboxRepository(db_session_factory)
    dispatcher = FakeDispatcher()

    async with db_session_factory() as session, session.begin():
        stmt = (
            insert(Tenant).values(id="t1", name="Test Tenant", slug="t1").on_conflict_do_nothing()
        )
        await session.execute(stmt)

    # 1. Insert a pending message into the outbox
    message = NotificationOutboxEvent(
        id="msg-123",
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
    await repo.save(message)

    processor = OutboxSweeperUseCase(repository=repo, publisher=dispatcher)

    # 2. Run a single poll cycle
    await processor.execute()

    # 3. Verify it was dispatched
    assert len(dispatcher.dispatches) == 1
    assert dispatcher.dispatches[0]["payload"]["channel"] == "EMAIL"
    assert dispatcher.dispatches[0]["tenant_id"] == "t1"

    # 4. Verify it was marked as COMPLETED in the database
    async with db_session_factory() as session:
        stmt = select(NotificationOutbox).where(NotificationOutbox.tenant_id == "t1")
        result = await session.execute(stmt)
        outbox_row = result.scalars().first()

        assert outbox_row is not None
        assert outbox_row.status == OutboxStatus.PROCESSED.value
        assert outbox_row.owner_token is not None
