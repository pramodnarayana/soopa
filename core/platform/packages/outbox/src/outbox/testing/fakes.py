from database.events import EventEnvelope
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort


class FakeOutboxCleanupRepository(OutboxCleanupRepositoryPort):
    def __init__(self) -> None:
        self.cleanup_calls: list[int] = []

    async def cleanup_outbox(self, retention_days: int) -> int:
        self.cleanup_calls.append(retention_days)
        return 42


class FakeOutboxPublisher(OutboxPublisherPort):
    def __init__(self) -> None:
        self.published_events: list[EventEnvelope] = []
        self.fail_on_publish = False

    async def publish(self, event: EventEnvelope) -> None:
        if self.fail_on_publish:
            raise RuntimeError("Mocked publish failure")
        self.published_events.append(event)

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        if self.fail_on_publish:
            raise RuntimeError("Mocked batch publish failure")
        self.published_events.extend(events)
        return [e.id for e in events]


class FakeOutboxRepository(OutboxRepositoryPort):
    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []
        self.stuck_events_swept = 0
        self.completed_events: list[tuple[str, str]] = []
        self.failed_events: list[tuple[str, str, str]] = []

    async def sweep_stuck_events(self, lock_lease_ms: int) -> int:
        self.stuck_events_swept += 5
        return 5

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[EventEnvelope]:
        return self.events[:limit]

    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        self.completed_events.append((event_id, worker_id))
        self.events = [e for e in self.events if e.id != event_id]

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
        self.failed_events.append((event_id, worker_id, error_message))
        self.events = [e for e in self.events if e.id != event_id]
