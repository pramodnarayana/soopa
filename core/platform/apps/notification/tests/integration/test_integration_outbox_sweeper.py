from typing import Any

import pytest
from platform_orm.models.notifications import NotificationOutbox
from sqlalchemy import select

from notification.adapters.outbound.postgres_outbox_repository import (
    PostgresOutboxRepository,
)
from notification.application.outbox_processor import NotificationOutboxProcessor
from notification.domain.models import Channel, NotificationOutboxEvent


class FakeDispatcher:
    def __init__(self):
        self.dispatches = []

    async def dispatch(
        self,
        channel: Channel,
        tenant_id: str,
        content: str,
        subject: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.dispatches.append(
            {
                "channel": channel,
                "tenant_id": tenant_id,
                "content": content,
                "subject": subject,
                "data": data,
            }
        )


@pytest.mark.asyncio
async def test_outbox_sweeper_integration(db_session_factory):
    """
    A High-Quality Narrow Integration Test that uses a real Postgres database
    to verify that the Outbox Sweeper successfully claims messages from the DB,
    processes them, and marks them as completed.
    """
    repo = PostgresOutboxRepository(db_session_factory)
    dispatcher = FakeDispatcher()

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

    processor = NotificationOutboxProcessor(
        repository=repo, dispatcher=dispatcher, worker_id="test_worker_1"
    )

    # 2. Run a single poll cycle
    await processor.process_pending()

    # 3. Verify it was dispatched
    assert len(dispatcher.dispatches) == 1
    assert dispatcher.dispatches[0]["channel"] == Channel.EMAIL
    assert dispatcher.dispatches[0]["tenant_id"] == "t1"

    # 4. Verify it was marked as COMPLETED in the database
    async with db_session_factory() as session:
        stmt = select(NotificationOutbox).where(NotificationOutbox.tenant_id == "t1")
        result = await session.execute(stmt)
        outbox_row = result.scalars().first()

        assert outbox_row is not None
        assert outbox_row.status == "COMPLETED"
        # Safe: dummy token for test
        assert outbox_row.owner_token == "test_worker_1"  # noqa: S105
