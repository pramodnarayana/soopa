import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from notification.domain.models import NotificationEvent

from notification_worker.adapters.inbound.workers.notification_event_sqs_consumer import (
    NotificationEventSqsConsumer,
)


class FakeDispatchUseCase:
    def __init__(self):
        self.events = []

    async def execute(self, event: NotificationEvent) -> None:
        self.events.append(event)


class FakeSweeperJobHandler:
    def __init__(self):
        self.executed = False

    async def execute(self) -> None:
        self.executed = True


@pytest.mark.asyncio
async def test_consumer_process_message_valid():
    use_case = FakeDispatchUseCase()
    sweeper_handler = FakeSweeperJobHandler()
    worker = NotificationEventSqsConsumer(use_case, sweeper_handler)

    body = {
        "event_type": "notification.triggered",
        "event": {
            "tenant_id": "t1",
            "payload": {"event_type": "invoice.paid", "invoice_id": "123"},
        },
    }

    await worker._process_message(body)

    assert len(use_case.events) == 1
    event = use_case.events[0]
    assert event.tenant_id == "t1"
    assert event.event_type == "invoice.paid"
    assert event.data["invoice_id"] == "123"
    assert event.data["tenant_id"] == "t1"


@pytest.mark.asyncio
async def test_consumer_process_message_missing_event():
    use_case = FakeDispatchUseCase()
    worker = NotificationEventSqsConsumer(use_case, FakeSweeperJobHandler())
    await worker._process_message({})
    assert len(use_case.events) == 0


@pytest.mark.asyncio
async def test_consumer_process_message_missing_payload():
    use_case = FakeDispatchUseCase()
    worker = NotificationEventSqsConsumer(use_case, FakeSweeperJobHandler())
    await worker._process_message({"event": {}})
    assert len(use_case.events) == 0


@pytest.mark.asyncio
async def test_consumer_process_sweeper_job():
    use_case = FakeDispatchUseCase()
    sweeper_handler = FakeSweeperJobHandler()
    worker = NotificationEventSqsConsumer(use_case, sweeper_handler)

    body = {
        "event_type": "NOTIFICATION_OUTBOX_SWEEPER",
    }

    await worker._process_message(body)

    # Sweeper should have been called
    assert sweeper_handler.executed
    # Dispatch use case should NOT be called
    assert len(use_case.events) == 0


@pytest.mark.asyncio
async def test_consumer_lifecycle():
    use_case = FakeDispatchUseCase()
    worker = NotificationEventSqsConsumer(use_case, FakeSweeperJobHandler())

    with patch(
        "notification_worker.adapters.inbound.workers.notification_event_sqs_consumer.AwsSqsConsumer",
        new_callable=AsyncMock,
    ) as mock_poll:
        # Prevent it from actually looping forever by making it sleep briefly then we stop it
        async def mock_poller(*args, **kwargs):
            await asyncio.sleep(0.1)

        mock_poll.side_effect = mock_poller

        task = worker.start()
        assert worker._task is not None

        # Calling start again shouldn't create a new task
        task2 = worker.start()
        assert task == task2

        await asyncio.sleep(0.01)
        await worker.stop()

        # Stop again is safe
        await worker.stop()

        await task

        assert worker._task is None
