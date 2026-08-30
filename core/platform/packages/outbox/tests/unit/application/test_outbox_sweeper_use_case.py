import asyncio
from unittest.mock import patch

import pytest
from database.events import EventEnvelope
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from outbox.testing.fakes import FakeOutboxPublisher, FakeOutboxRepository


def _event(event_id: str) -> EventEnvelope:
    return EventEnvelope(
        id=event_id,
        source="test",
        event_type="test.event",
        tenant_id="tenant-1",
        idempotency_key=event_id,
        payload={},
    )


@pytest.mark.asyncio
async def test_sweeper_sweeps_stuck_events_before_draining():
    """Verifies that sweep_stuck_events is called before claim_next_events."""
    repository = FakeOutboxRepository()
    repository.events = []

    class TrackSweepFakeRepository(FakeOutboxRepository):
        def __init__(self):
            super().__init__()
            self.sweep_called = False
            self.claim_called = False

        async def sweep_stuck_events(self, lock_lease_ms: int) -> int:
            self.sweep_called = True
            return 3

        async def claim_next_events(
            self, worker_id: str, limit: int, lock_lease_ms: int
        ) -> list[EventEnvelope]:
            assert self.sweep_called is True
            self.claim_called = True
            return []

    track_repo = TrackSweepFakeRepository()
    publisher = FakeOutboxPublisher()
    sweeper = OutboxSweeperUseCase(repository=track_repo, publisher=publisher)

    await sweeper.execute()

    assert track_repo.sweep_called is True
    assert track_repo.claim_called is True


@pytest.mark.asyncio
async def test_sweeper_drains_all_pending_events():
    """Verifies that the sweeper loops until the outbox is empty."""
    repository = FakeOutboxRepository()
    repository.events = [_event("evt-1"), _event("evt-2")]

    class DrainFakeRepository(FakeOutboxRepository):
        def __init__(self):
            super().__init__()
            self.events = [_event("evt-1"), _event("evt-2")]
            self.claims_made = 0

        async def claim_next_events(
            self, worker_id: str, limit: int, lock_lease_ms: int
        ) -> list[EventEnvelope]:
            self.claims_made += 1
            if self.claims_made == 1:
                return self.events
            return []

        async def mark_completed(self, event_id: str, worker_id: str) -> None:
            self.completed_events.append((event_id, worker_id))

    drain_repo = DrainFakeRepository()
    publisher = FakeOutboxPublisher()
    sweeper = OutboxSweeperUseCase(repository=drain_repo, publisher=publisher)

    future = asyncio.Future()
    future.set_result(None)
    with patch("asyncio.sleep", return_value=future):
        await sweeper.execute()

    assert drain_repo.claims_made == 2
    assert len(drain_repo.completed_events) == 2


@pytest.mark.asyncio
async def test_sweeper_marks_failed_events_that_were_not_published():
    """Verifies partial failures: successful events are completed; failed are marked_failed."""

    class PartialFakePublisher(FakeOutboxPublisher):
        async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
            return ["evt-1"]

    repository = FakeOutboxRepository()
    repository.events = [_event("evt-1"), _event("evt-2")]

    class DrainFakeRepository(FakeOutboxRepository):
        def __init__(self):
            super().__init__()
            self.events = [_event("evt-1"), _event("evt-2")]
            self.claims_made = 0

        async def claim_next_events(
            self, worker_id: str, limit: int, lock_lease_ms: int
        ) -> list[EventEnvelope]:
            self.claims_made += 1
            if self.claims_made == 1:
                return self.events
            return []

    drain_repo = DrainFakeRepository()
    publisher = PartialFakePublisher()

    sweeper = OutboxSweeperUseCase(repository=drain_repo, publisher=publisher)

    future = asyncio.Future()
    future.set_result(None)
    with patch("asyncio.sleep", return_value=future):
        await sweeper.execute()

    assert len(drain_repo.completed_events) == 1
    assert drain_repo.completed_events[0] == ("evt-1", sweeper.worker_id)
    assert len(drain_repo.failed_events) == 1
    assert drain_repo.failed_events[0][0] == "evt-2"


@pytest.mark.asyncio
async def test_sweeper_handles_batch_publisher_exception_gracefully():
    """When publisher.publish_batch raises, all events are marked_failed; sweeper does not crash."""
    repository = FakeOutboxRepository()
    repository.events = [_event("evt-1"), _event("evt-2")]

    class DrainFakeRepository(FakeOutboxRepository):
        def __init__(self):
            super().__init__()
            self.events = [_event("evt-1"), _event("evt-2")]
            self.claims_made = 0

        async def claim_next_events(
            self, worker_id: str, limit: int, lock_lease_ms: int
        ) -> list[EventEnvelope]:
            self.claims_made += 1
            if self.claims_made == 1:
                return self.events
            return []

    drain_repo = DrainFakeRepository()
    publisher = FakeOutboxPublisher()
    publisher.fail_on_publish = True

    sweeper = OutboxSweeperUseCase(repository=drain_repo, publisher=publisher)

    future = asyncio.Future()
    future.set_result(None)
    with patch("asyncio.sleep", return_value=future):
        await sweeper.execute()  # must not raise

    assert len(drain_repo.completed_events) == 0
    assert len(drain_repo.failed_events) == 2


@pytest.mark.asyncio
async def test_sweeper_handles_mark_completed_exception_gracefully():
    """_safe_mark_completed swallows repository errors to avoid aborting the batch."""

    class FailingCompleteRepo(FakeOutboxRepository):
        def __init__(self):
            super().__init__()
            self.events = [_event("evt-1")]
            self.claims_made = 0

        async def claim_next_events(
            self, worker_id: str, limit: int, lock_lease_ms: int
        ) -> list[EventEnvelope]:
            self.claims_made += 1
            if self.claims_made == 1:
                return self.events
            return []

        async def mark_completed(self, event_id: str, worker_id: str) -> None:
            raise RuntimeError("DB connection lost")

    repo = FailingCompleteRepo()
    publisher = FakeOutboxPublisher()
    sweeper = OutboxSweeperUseCase(repository=repo, publisher=publisher)

    future = asyncio.Future()
    future.set_result(None)
    with patch("asyncio.sleep", return_value=future):
        await sweeper.execute()


@pytest.mark.asyncio
async def test_sweeper_handles_mark_failed_exception_gracefully():
    """_safe_mark_failed swallows repository errors to avoid aborting the batch."""

    class FailingMarkFailedRepo(FakeOutboxRepository):
        def __init__(self):
            super().__init__()
            self.events = [_event("evt-1")]
            self.claims_made = 0

        async def claim_next_events(
            self, worker_id: str, limit: int, lock_lease_ms: int
        ) -> list[EventEnvelope]:
            self.claims_made += 1
            if self.claims_made == 1:
                return self.events
            return []

        async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
            raise RuntimeError("DB connection lost")

    repo = FailingMarkFailedRepo()

    class EmptyPublisher(FakeOutboxPublisher):
        async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
            return []

    sweeper = OutboxSweeperUseCase(repository=repo, publisher=EmptyPublisher())

    future = asyncio.Future()
    future.set_result(None)
    with patch("asyncio.sleep", return_value=future):
        await sweeper.execute()


@pytest.mark.asyncio
async def test_sweeper_is_no_op_when_outbox_is_empty():
    """When no events exist and nothing is stuck, sweeper terminates immediately."""

    class TrackNoOpRepo(FakeOutboxRepository):
        def __init__(self):
            super().__init__()
            self.mark_completed_called = False
            self.mark_failed_called = False

        async def mark_completed(self, event_id: str, worker_id: str) -> None:
            self.mark_completed_called = True

        async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
            self.mark_failed_called = True

    repo = TrackNoOpRepo()

    class TrackPublisher(FakeOutboxPublisher):
        def __init__(self):
            super().__init__()
            self.publish_called = False

        async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
            self.publish_called = True
            return []

    publisher = TrackPublisher()

    sweeper = OutboxSweeperUseCase(repository=repo, publisher=publisher)
    await sweeper.execute()

    assert publisher.publish_called is False
    assert repo.mark_completed_called is False
    assert repo.mark_failed_called is False
