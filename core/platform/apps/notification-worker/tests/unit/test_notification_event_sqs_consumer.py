import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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


class FakeSqsConsumer:
    queue_name = "test-notifications"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        return None

    @asynccontextmanager
    async def poll_raw_message(self) -> AsyncIterator[dict | None]:
        await asyncio.sleep(0.01)
        yield None


def make_worker(
    use_case: FakeDispatchUseCase,
    sweeper_handler: FakeSweeperJobHandler,
) -> NotificationEventSqsConsumer:
    return NotificationEventSqsConsumer(
        consumer=FakeSqsConsumer(),
        notification_compiler=use_case,
        cleanup_job_handler=sweeper_handler,
    )


@pytest.mark.asyncio
async def test_consumer_process_message_valid():
    use_case = FakeDispatchUseCase()
    sweeper_handler = FakeSweeperJobHandler()
    worker = make_worker(use_case, sweeper_handler)

    body = {
        "event_type": "notification.requested",
        "payload": {
            "event": {
                "event_type": "invoice.paid",
                "tenant_id": "t1",
                "payload": {"invoice_id": "123"},
            }
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
    worker = make_worker(use_case, FakeSweeperJobHandler())
    await worker._process_message({})
    assert len(use_case.events) == 0


@pytest.mark.asyncio
async def test_consumer_process_message_missing_payload():
    use_case = FakeDispatchUseCase()
    worker = make_worker(use_case, FakeSweeperJobHandler())
    await worker._process_message({"payload": {"event": {}}})
    assert len(use_case.events) == 0


@pytest.mark.asyncio
async def test_consumer_process_sweeper_job():
    use_case = FakeDispatchUseCase()
    sweeper_handler = FakeSweeperJobHandler()
    worker = make_worker(use_case, sweeper_handler)

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
    worker = make_worker(use_case, FakeSweeperJobHandler())

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
