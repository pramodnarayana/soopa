import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from notification.application.consumer import NotificationConsumerWorker
from notification.domain.models import NotificationEvent


class FakeDispatchUseCase:
    def __init__(self):
        self.events = []

    async def execute(self, event: NotificationEvent) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_consumer_process_message_valid():
    use_case = FakeDispatchUseCase()
    worker = NotificationConsumerWorker(use_case)  # type: ignore

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
    worker = NotificationConsumerWorker(use_case)  # type: ignore
    await worker._process_message({})
    assert len(use_case.events) == 0


@pytest.mark.asyncio
async def test_consumer_process_message_missing_payload():
    use_case = FakeDispatchUseCase()
    worker = NotificationConsumerWorker(use_case)  # type: ignore
    await worker._process_message({"event": {}})
    assert len(use_case.events) == 0


@pytest.mark.asyncio
async def test_consumer_lifecycle():
    use_case = FakeDispatchUseCase()
    worker = NotificationConsumerWorker(use_case)  # type: ignore

    with patch(
        "notification.application.consumer.poll_sqs_queue", new_callable=AsyncMock
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
