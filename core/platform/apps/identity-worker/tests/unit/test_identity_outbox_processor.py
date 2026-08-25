import uuid

import pytest
from identity_worker.application.use_cases.identity_outbox_processor_use_case import (
    IdentityOutboxProcessorUseCase,
)
from identity_worker.ports.outbound.outbox_publisher_port import OutboxPublisherPort
from identity_worker.ports.outbound.outbox_repository_port import OutboxRepositoryPort
from platform_orm.events import EventEnvelope

pytestmark = pytest.mark.asyncio


class FakeOutboxRepository(OutboxRepositoryPort):
    def __init__(self):
        self.events: list[EventEnvelope] = []
        self.completed = set()
        self.failed = set()

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[EventEnvelope]:
        # Return events that haven't been completed or failed
        unprocessed = [
            e for e in self.events if e.id not in self.completed and e.id not in self.failed
        ]
        return unprocessed[:limit]

    async def sweep_stuck_events(self, lock_lease_ms: int) -> int:
        return 0

    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        self.completed.add(event_id)

    async def mark_failed(self, event_id: str, worker_id: str, error: str) -> None:
        self.failed.add(event_id)


class FakeOutboxPublisher(OutboxPublisherPort):
    def __init__(self, fail_on_publish=False):
        self.published = []
        self.fail_on_publish = fail_on_publish

    async def publish(self, event: EventEnvelope) -> None:
        if self.fail_on_publish:
            raise RuntimeError("Simulated publish failure")
        self.published.append(event)


@pytest.fixture
def test_event():
    return EventEnvelope(
        id=str(uuid.uuid4()),
        source="identity",
        event_type="UserCreated",
        tenant_id=None,
        idempotency_key=None,
        payload={"email": "test@test.com"},
    )


async def test_process_pending_success(test_event):
    repo = FakeOutboxRepository()
    repo.events.append(test_event)

    publisher = FakeOutboxPublisher()
    processor = IdentityOutboxProcessorUseCase(repo, publisher)

    # Run processor
    has_more = await processor.process_pending()

    assert has_more is False
    assert len(publisher.published) == 1
    assert publisher.published[0].id == test_event.id
    assert test_event.id in repo.completed


async def test_process_pending_failure_handling(test_event):
    repo = FakeOutboxRepository()
    repo.events.append(test_event)

    # Setup publisher to fail
    publisher = FakeOutboxPublisher(fail_on_publish=True)
    processor = IdentityOutboxProcessorUseCase(repo, publisher)

    has_more = await processor.process_pending()

    assert has_more is False
    assert len(publisher.published) == 0
    assert test_event.id in repo.failed
    assert test_event.id not in repo.completed


async def test_process_pending_batch_limit():
    repo = FakeOutboxRepository()
    for _ in range(5):
        repo.events.append(
            EventEnvelope(
                id=str(uuid.uuid4()),
                source="identity",
                event_type="Ping",
                tenant_id=None,
                idempotency_key=None,
                payload={},
            )
        )

    publisher = FakeOutboxPublisher()

    # Set limit to 2
    processor = IdentityOutboxProcessorUseCase(repo, publisher, max_concurrent_events=2)

    has_more = await processor.process_pending()

    # Should process exactly 2 events and return True (more available)
    assert has_more is True
    assert len(publisher.published) == 2
    assert len(repo.completed) == 2
