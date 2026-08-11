import asyncio
from typing import Any

import pytest

from notification_engine.application.outbox_sweeper import NotificationOutboxSweeper
from notification_engine.domain.models import Channel


class FakeOutboxRepo:
    def __init__(self):
        self.messages = []
        self.swept = 0
        self.completed = []
        self.failed = []

    async def sweep_stuck_messages(self, lock_lease_ms: int) -> int:
        return self.swept

    async def claim_next_messages(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[Any]:
        return self.messages[:limit]

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
async def test_outbox_sweeper_poll_success():
    repo = FakeOutboxRepo()
    dispatcher = FakeDispatcher()

    msg = FakeMessage(
        "m1",
        "t1",
        {"channel": "EMAIL", "content": "Hello", "subject": "Subj", "data": {"foo": "bar"}},
    )
    repo.messages = [msg]
    repo.swept = 2

    sweeper = NotificationOutboxSweeper(repo, dispatcher, worker_id="w1", poll_interval_seconds=0)  # type: ignore

    await sweeper.poll()

    assert len(dispatcher.dispatches) == 1
    assert dispatcher.dispatches[0]["channel"] == Channel.EMAIL
    assert len(repo.completed) == 1
    assert repo.completed[0] == "m1"
    assert len(repo.failed) == 0


@pytest.mark.asyncio
async def test_outbox_sweeper_poll_failure():
    repo = FakeOutboxRepo()
    dispatcher = FakeDispatcher()
    dispatcher.should_fail = True

    msg = FakeMessage(
        "m2", "t1", {"channel": "IN_APP", "content": "Hello", "subject": "Subj", "data": {}}
    )
    repo.messages = [msg]

    sweeper = NotificationOutboxSweeper(repo, dispatcher, worker_id="w1", poll_interval_seconds=0)  # type: ignore

    await sweeper.poll()

    assert len(dispatcher.dispatches) == 0
    assert len(repo.completed) == 0
    assert len(repo.failed) == 1
    assert repo.failed[0][0] == "m2"
    assert "Dispatch failed" in repo.failed[0][1]


@pytest.mark.asyncio
async def test_outbox_sweeper_lifecycle():
    repo = FakeOutboxRepo()
    dispatcher = FakeDispatcher()

    sweeper = NotificationOutboxSweeper(repo, dispatcher, worker_id="w1", poll_interval_seconds=0)  # type: ignore

    task = sweeper.start()
    assert sweeper.is_running is True

    # Wait for one loop iteration
    await asyncio.sleep(0.01)

    sweeper.stop()
    await task

    assert sweeper.is_running is False
