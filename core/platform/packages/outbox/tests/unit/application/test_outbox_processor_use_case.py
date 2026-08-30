import pytest
from database.events import EventEnvelope
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
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
async def test_batch_exception_reason_is_preserved_for_retry_transition():
    repository = FakeOutboxRepository()
    repository.events = [_event("event-1")]
    publisher = FakeOutboxPublisher()
    publisher.fail_on_publish = True
    processor = OutboxProcessorUseCase(repository, publisher, worker_id="worker-1")

    await processor.process_pending()

    assert len(repository.failed_events) == 1
    assert repository.failed_events[0][0] == "event-1"
    assert repository.failed_events[0][1] == "worker-1"
    assert "Mocked batch publish failure" in repository.failed_events[0][2]
    assert len(repository.completed_events) == 0


@pytest.mark.asyncio
async def test_partial_batch_result_completes_successes_and_retries_remainder():
    repository = FakeOutboxRepository()
    repository.events = [_event("event-1"), _event("event-2")]

    class PartialFakePublisher(FakeOutboxPublisher):
        async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
            return ["event-1"]

    publisher = PartialFakePublisher()
    processor = OutboxProcessorUseCase(repository, publisher, worker_id="worker-1")

    await processor.process_pending()

    assert len(repository.completed_events) == 1
    assert repository.completed_events[0] == ("event-1", "worker-1")
    assert len(repository.failed_events) == 1
    assert repository.failed_events[0][0] == "event-2"
    assert repository.failed_events[0][1] == "worker-1"


@pytest.mark.asyncio
async def test_process_pending_returns_false_when_stopped():
    """process_pending returns False immediately when processor has been stopped."""
    repository = FakeOutboxRepository()
    repository.events = [_event("event-1")]
    publisher = FakeOutboxPublisher()
    processor = OutboxProcessorUseCase(repository, publisher, worker_id="worker-1")

    processor.stop()
    result = await processor.process_pending()

    assert result is False
    assert len(repository.events) == 1  # Not claimed


@pytest.mark.asyncio
async def test_process_pending_returns_false_when_no_events():
    """process_pending returns False when outbox is empty."""
    repository = FakeOutboxRepository()
    publisher = FakeOutboxPublisher()
    processor = OutboxProcessorUseCase(repository, publisher, worker_id="worker-1")

    result = await processor.process_pending()

    assert result is False
    assert len(publisher.published_events) == 0


@pytest.mark.asyncio
async def test_process_pending_returns_true_when_batch_is_full():
    """process_pending returns True when events claimed == max_concurrent (more may exist)."""
    repository = FakeOutboxRepository()
    repository.events = [_event(f"evt-{i}") for i in range(2)]
    publisher = FakeOutboxPublisher()
    processor = OutboxProcessorUseCase(
        repository, publisher, max_concurrent_events=2, worker_id="worker-1"
    )

    result = await processor.process_pending()

    assert result is True


@pytest.mark.asyncio
async def test_process_pending_uses_batch_failure_reason_when_publisher_returns_empty():
    """When publisher returns empty list without raising, a generic failure reason is used."""
    repository = FakeOutboxRepository()
    repository.events = [_event("evt-1")]

    class EmptyFakePublisher(FakeOutboxPublisher):
        async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
            return []

    publisher = EmptyFakePublisher()
    processor = OutboxProcessorUseCase(repository, publisher, worker_id="worker-1")
    await processor.process_pending()

    assert len(repository.failed_events) == 1
    assert repository.failed_events[0][0] == "evt-1"
    assert (
        "no successful event ids" in repository.failed_events[0][2].lower()
        or "not acknowledged" in repository.failed_events[0][2].lower()
    )
