from typing import Any

import pytest

from notification.application.outbox_processor import NotificationOutboxProcessor
from notification.application.sweep_outbox_use_case import SweepNotificationOutboxUseCase
from notification.domain.models import Channel


class FakeOutboxRepo:
    def __init__(self):
        self.messages = []
        self.swept = 0
        self.completed = []
        self.failed = []
        self.sweep_calls = []

    async def sweep_stuck_messages(self, lock_lease_ms: int) -> int:
        self.sweep_calls.append(lock_lease_ms)
        return self.swept

    async def claim_next_messages(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[Any]:
        # Return all messages and clear them so it breaks the while loop in process_pending
        msgs = self.messages[:limit]
        self.messages = self.messages[limit:]
        return msgs

    async def mark_completed(self, message_id: str, worker_id: str) -> None:
        self.completed.append(message_id)

    async def mark_failed(self, message_id: str, worker_id: str, error: str) -> None:
        self.failed.append((message_id, error))


class FakeDispatcher:
    def __init__(self):
        self.dispatches = []
        self.should_fail = False

    async def dispatch(
        self,
        channel: Channel,
        tenant_id: str,
        content: str,
        subject: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if self.should_fail:
            raise RuntimeError("Dispatch failed")
        self.dispatches.append(
            {
                "channel": channel,
                "tenant_id": tenant_id,
                "content": content,
                "subject": subject,
                "data": data,
            }
        )


class FakeMessage:
    def __init__(self, id, tenant_id, payload):
        self.id = id
        self.tenant_id = tenant_id
        self.payload = payload


@pytest.mark.asyncio
async def test_outbox_processor_success():
    repo = FakeOutboxRepo()
    dispatcher = FakeDispatcher()

    msg = FakeMessage(
        "m1",
        "t1",
        {"channel": "EMAIL", "content": "Hello", "subject": "Subj", "data": {"foo": "bar"}},
    )
    repo.messages = [msg]

    processor = NotificationOutboxProcessor(repo, dispatcher, worker_id="w1")

    await processor.process_pending()

    assert len(dispatcher.dispatches) == 1
    assert dispatcher.dispatches[0]["channel"] == Channel.EMAIL
    assert len(repo.completed) == 1
    assert repo.completed[0] == "m1"
    assert len(repo.failed) == 0


@pytest.mark.asyncio
async def test_outbox_processor_failure():
    repo = FakeOutboxRepo()
    dispatcher = FakeDispatcher()
    dispatcher.should_fail = True

    msg = FakeMessage(
        "m2", "t1", {"channel": "IN_APP", "content": "Hello", "subject": "Subj", "data": {}}
    )
    repo.messages = [msg]

    processor = NotificationOutboxProcessor(repo, dispatcher, worker_id="w1")

    await processor.process_pending()

    assert len(dispatcher.dispatches) == 0
    assert len(repo.completed) == 0
    assert len(repo.failed) == 1
    assert repo.failed[0][0] == "m2"
    assert "Dispatch failed" in repo.failed[0][1]


@pytest.mark.asyncio
async def test_sweep_stuck_messages():
    repo = FakeOutboxRepo()
    repo.swept = 5

    sweeper = SweepNotificationOutboxUseCase(repo)

    await sweeper.execute()

    # The repo.sweep_stuck_messages was called and it should have returned 5.
    # Verify it was called with the expected lease value
    assert len(repo.sweep_calls) == 1
    assert repo.sweep_calls[0] == 30000  # Default lease in SweepNotificationOutboxUseCase
    assert repo.swept == 5
