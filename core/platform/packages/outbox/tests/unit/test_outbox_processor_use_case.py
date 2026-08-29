from unittest.mock import AsyncMock

import pytest
from database.events import EventEnvelope
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase


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
async def test_batch_exception_reason_is_preserved_for_retry_transition():
    repository = AsyncMock()
    repository.claim_next_events.return_value = [_event("event-1")]
    publisher = AsyncMock()
    publisher.publish_batch.side_effect = RuntimeError("transport unavailable")
    processor = OutboxProcessorUseCase(repository, publisher, worker_id="worker-1")

    await processor.process_pending()

    repository.mark_failed.assert_awaited_once_with("event-1", "worker-1", "transport unavailable")
    repository.mark_completed.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_batch_result_completes_successes_and_retries_remainder():
    repository = AsyncMock()
    repository.claim_next_events.return_value = [_event("event-1"), _event("event-2")]
    publisher = AsyncMock()
    publisher.publish_batch.return_value = ["event-1"]
    processor = OutboxProcessorUseCase(repository, publisher, worker_id="worker-1")

    await processor.process_pending()

    repository.mark_completed.assert_awaited_once_with("event-1", "worker-1")
    failed_args = repository.mark_failed.await_args.args
    assert failed_args[:2] == ("event-2", "worker-1")


@pytest.mark.asyncio
async def test_process_pending_returns_false_when_stopped():
    """process_pending returns False immediately when processor has been stopped."""
    repository = AsyncMock()
    publisher = AsyncMock()
    processor = OutboxProcessorUseCase(repository, publisher, worker_id="worker-1")

    processor.stop()
    result = await processor.process_pending()

    assert result is False
    repository.claim_next_events.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_pending_returns_false_when_no_events():
    """process_pending returns False when outbox is empty."""
    repository = AsyncMock()
    repository.claim_next_events.return_value = []
    publisher = AsyncMock()
    processor = OutboxProcessorUseCase(repository, publisher, worker_id="worker-1")

    result = await processor.process_pending()

    assert result is False
    publisher.publish_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_pending_returns_true_when_batch_is_full():
    """process_pending returns True when events claimed == max_concurrent (more may exist)."""
    repository = AsyncMock()
    repository.claim_next_events.return_value = [_event(f"evt-{i}") for i in range(2)]
    publisher = AsyncMock()
    publisher.publish_batch.return_value = [f"evt-{i}" for i in range(2)]
    processor = OutboxProcessorUseCase(
        repository, publisher, max_concurrent_events=2, worker_id="worker-1"
    )

    result = await processor.process_pending()

    assert result is True


@pytest.mark.asyncio
async def test_process_pending_uses_batch_failure_reason_when_publisher_returns_empty():
    """When publisher returns empty list without raising, a generic failure reason is used."""
    repository = AsyncMock()
    repository.claim_next_events.return_value = [_event("evt-1")]
    publisher = AsyncMock()
    publisher.publish_batch.return_value = []  # all events failed, no exception raised

    processor = OutboxProcessorUseCase(repository, publisher, worker_id="worker-1")
    await processor.process_pending()

    failed_args = repository.mark_failed.await_args.args
    assert failed_args[0] == "evt-1"
    assert (
        "no successful event ids" in failed_args[2].lower()
        or "not acknowledged" in failed_args[2].lower()
    )
