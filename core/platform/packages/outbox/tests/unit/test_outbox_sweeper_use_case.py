from unittest.mock import AsyncMock, patch

import pytest
from database.events import EventEnvelope
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase


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
    repository = AsyncMock()
    repository.sweep_stuck_events.return_value = 3
    repository.claim_next_events.return_value = []  # empty outbox after sweep

    publisher = AsyncMock()
    sweeper = OutboxSweeperUseCase(repository=repository, publisher=publisher)

    await sweeper.execute()

    repository.sweep_stuck_events.assert_awaited_once_with(sweeper.lock_lease_ms)
    repository.claim_next_events.assert_awaited_once()


@pytest.mark.asyncio
async def test_sweeper_drains_all_pending_events():
    """Verifies that the sweeper loops until the outbox is empty."""
    repository = AsyncMock()
    repository.sweep_stuck_events.return_value = 0
    # First call returns 2 events, second call returns empty (outbox drained)
    repository.claim_next_events.side_effect = [
        [_event("evt-1"), _event("evt-2")],
        [],
    ]
    publisher = AsyncMock()
    publisher.publish_batch.return_value = ["evt-1", "evt-2"]

    sweeper = OutboxSweeperUseCase(repository=repository, publisher=publisher)

    with patch("asyncio.sleep", new_callable=AsyncMock):  # skip real sleep
        await sweeper.execute()

    assert repository.claim_next_events.await_count == 2
    assert repository.mark_completed.await_count == 2


@pytest.mark.asyncio
async def test_sweeper_marks_failed_events_that_were_not_published():
    """Verifies partial failures: successful events are completed; failed are marked_failed."""
    repository = AsyncMock()
    repository.sweep_stuck_events.return_value = 0
    repository.claim_next_events.side_effect = [
        [_event("evt-1"), _event("evt-2")],
        [],
    ]
    publisher = AsyncMock()
    publisher.publish_batch.return_value = ["evt-1"]  # only evt-1 succeeded

    sweeper = OutboxSweeperUseCase(repository=repository, publisher=publisher)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await sweeper.execute()

    repository.mark_completed.assert_awaited_once_with("evt-1", sweeper.worker_id)
    repository.mark_failed.assert_awaited_once_with(
        "evt-2", sweeper.worker_id, "Failed to publish in batch"
    )


@pytest.mark.asyncio
async def test_sweeper_handles_batch_publisher_exception_gracefully():
    """When publisher.publish_batch raises, all events are marked_failed; sweeper does not crash."""
    repository = AsyncMock()
    repository.sweep_stuck_events.return_value = 0
    repository.claim_next_events.side_effect = [
        [_event("evt-1"), _event("evt-2")],
        [],
    ]
    publisher = AsyncMock()
    publisher.publish_batch.side_effect = RuntimeError("SNS unreachable")

    sweeper = OutboxSweeperUseCase(repository=repository, publisher=publisher)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await sweeper.execute()  # must not raise

    assert repository.mark_completed.await_count == 0
    assert repository.mark_failed.await_count == 2


@pytest.mark.asyncio
async def test_sweeper_handles_mark_completed_exception_gracefully():
    """_safe_mark_completed swallows repository errors to avoid aborting the batch."""
    repository = AsyncMock()
    repository.sweep_stuck_events.return_value = 0
    repository.claim_next_events.side_effect = [
        [_event("evt-1")],
        [],
    ]
    repository.mark_completed.side_effect = RuntimeError("DB connection lost")
    publisher = AsyncMock()
    publisher.publish_batch.return_value = ["evt-1"]

    sweeper = OutboxSweeperUseCase(repository=repository, publisher=publisher)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await sweeper.execute()  # must not raise despite DB error on mark_completed


@pytest.mark.asyncio
async def test_sweeper_handles_mark_failed_exception_gracefully():
    """_safe_mark_failed swallows repository errors to avoid aborting the batch."""
    repository = AsyncMock()
    repository.sweep_stuck_events.return_value = 0
    repository.claim_next_events.side_effect = [
        [_event("evt-1")],
        [],
    ]
    repository.mark_failed.side_effect = RuntimeError("DB connection lost")
    publisher = AsyncMock()
    publisher.publish_batch.return_value = []  # all failed to publish

    sweeper = OutboxSweeperUseCase(repository=repository, publisher=publisher)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await sweeper.execute()  # must not raise despite DB error on mark_failed


@pytest.mark.asyncio
async def test_sweeper_is_no_op_when_outbox_is_empty():
    """When no events exist and nothing is stuck, sweeper terminates immediately."""
    repository = AsyncMock()
    repository.sweep_stuck_events.return_value = 0
    repository.claim_next_events.return_value = []
    publisher = AsyncMock()

    sweeper = OutboxSweeperUseCase(repository=repository, publisher=publisher)
    await sweeper.execute()

    publisher.publish_batch.assert_not_awaited()
    repository.mark_completed.assert_not_awaited()
    repository.mark_failed.assert_not_awaited()
