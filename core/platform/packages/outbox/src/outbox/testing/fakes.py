from collections.abc import Sequence

from outbox.domain.models import LogicalStreamEmissionResult
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from outbox.ports.shard_outbox_drain_port import ShardOutboxDrainPort
from outbox.ports.transactional_stream_emitter_port import TransactionalStreamEmitterPort
from seedwork.events import EventEnvelope


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
            raise RuntimeError("Faked publish failure")
        self.published_events.append(event)

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        if self.fail_on_publish:
            raise RuntimeError("Faked batch publish failure")
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

    async def mark_completed_batch(self, event_ids: Sequence[str], worker_id: str) -> None:
        for event_id in event_ids:
            await self.mark_completed(event_id, worker_id)

    async def mark_failed_batch(
        self, event_ids: Sequence[str], worker_id: str, error_message: str
    ) -> None:
        for event_id in event_ids:
            await self.mark_failed(event_id, worker_id, error_message)


class FakeTransactionalStreamEmitter(TransactionalStreamEmitterPort):
    """In-memory deterministic fake for `TransactionalStreamEmitterPort`."""

    def __init__(self) -> None:
        self.emitted_envelopes: list[EventEnvelope] = []
        self._watermark_seq: int = 1000

    async def emit_transactional_batch(
        self,
        envelopes: Sequence[EventEnvelope],
    ) -> LogicalStreamEmissionResult:
        if not envelopes:
            return LogicalStreamEmissionResult(emitted_count=0, high_watermark=None)
        for env in envelopes:
            self.emitted_envelopes.append(env)
            self._watermark_seq += 64
        return LogicalStreamEmissionResult(
            emitted_count=len(envelopes),
            high_watermark=self._watermark_seq,
        )


class FakeShardOutboxDrainRepository(ShardOutboxDrainPort):
    """In-memory multi-shard outbox fake tracking batch claims and single-query completions."""

    def __init__(self, shard_events: dict[str, list[EventEnvelope]] | None = None) -> None:
        self.shard_events = {k: list(v) for k, v in (shard_events or {}).items()}
        self.completed_batches: list[tuple[str, tuple[str, ...], str]] = []
        self.failed_batches: list[tuple[str, tuple[str, ...], str, str]] = []
        self.dead_letter_batches: list[tuple[str, tuple[str, ...], str, str]] = []
        self.claim_calls_per_shard: dict[str, int] = {k: 0 for k in self.shard_events}

    async def list_shards(self) -> list[tuple[str, str]]:
        return [(name, f"fake-shard://{name}") for name in self.shard_events]

    async def claim_shard_events(
        self,
        *,
        shard_name: str,
        shard_dsn: str,
        worker_id: str,
        limit: int,
        lock_lease_ms: int,
    ) -> list[EventEnvelope]:
        self.claim_calls_per_shard[shard_name] = self.claim_calls_per_shard.get(shard_name, 0) + 1
        pending = self.shard_events.get(shard_name, [])
        claimed = pending[:limit]
        self.shard_events[shard_name] = pending[limit:]
        return claimed

    async def mark_shard_completed_batch(
        self,
        *,
        shard_name: str,
        shard_dsn: str,
        event_ids: Sequence[str],
        worker_id: str,
    ) -> None:
        self.completed_batches.append((shard_name, tuple(event_ids), worker_id))

    async def mark_shard_failed_batch(
        self,
        *,
        shard_name: str,
        shard_dsn: str,
        event_ids: Sequence[str],
        worker_id: str,
        error_message: str,
        retry_delay_seconds: int | None = None,
    ) -> list[str]:
        del retry_delay_seconds
        self.failed_batches.append((shard_name, tuple(event_ids), worker_id, error_message))
        return []

    async def mark_shard_dead_letter_batch(
        self,
        *,
        shard_name: str,
        shard_dsn: str,
        event_ids: Sequence[str],
        worker_id: str,
        error_message: str,
    ) -> None:
        self.dead_letter_batches.append((shard_name, tuple(event_ids), worker_id, error_message))
