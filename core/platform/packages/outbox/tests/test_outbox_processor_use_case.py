from unittest.mock import AsyncMock

import pytest
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from platform_orm.events import EventEnvelope


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
