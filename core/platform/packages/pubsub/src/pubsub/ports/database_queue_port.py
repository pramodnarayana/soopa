"""Outbound Port protocol for the durable PostgreSQL Single-Queue Engine."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.events import EventEnvelope

from pubsub.domain.dtos import EventDispatchOutcome


@runtime_checkable
class DirectBatchDispatcherPort(OutboxPublisherPort, Protocol):
    """Outbound Port returning first-class per-event dispositions (ACK/NACK/DLQ + retry delay)."""

    async def dispatch_batch_outcomes(
        self,
        events: Sequence[EventEnvelope],
    ) -> list[EventDispatchOutcome]:
        """Dispatches a batch of events and returns structured per-event verdicts."""
        ...


@runtime_checkable
class DatabaseQueuePort(Protocol):
    """Port for durable, transactional, cross-container PostgreSQL queue storage."""

    async def enqueue(self, queue_name: str, event: EventEnvelope) -> None:
        """Persists a single EventEnvelope into the durable queue."""
        ...

    async def enqueue_batch(self, queue_name: str, events: Sequence[EventEnvelope]) -> list[str]:
        """Persists a batch of EventEnvelopes atomically and returns their event IDs."""
        ...

    async def register_subscription(
        self,
        topic_name: str,
        target_queue: str,
        *,
        event_types: Sequence[str] | None = None,
    ) -> None:
        """Idempotently registers a consumer queue's subscription to a logical pub/sub topic."""
        ...

    async def publish_to_topic(self, topic_name: str, event: EventEnvelope) -> list[str]:
        """Atomically fans out a single EventEnvelope to all matching active subscriber queues."""
        ...

    async def publish_batch_to_topic(
        self,
        topic_name: str,
        events: Sequence[EventEnvelope],
    ) -> list[str]:
        """Atomically fans out a batch of EventEnvelopes to all matching active subscriber queues."""
        ...

    async def claim_batch(
        self,
        queue_name: str,
        worker_id: str,
        limit: int = 500,
        lock_lease_ms: int = 30000,
    ) -> list[EventEnvelope]:
        """Claims up to `limit` pending or lease-expired events via `FOR UPDATE SKIP LOCKED`."""
        ...

    async def mark_completed_batch(
        self,
        queue_name: str,
        event_ids: Sequence[str],
        worker_id: str,
    ) -> None:
        """Marks claimed events as `PROCESSED` in a single batch statement."""
        ...

    async def mark_failed_batch(
        self,
        queue_name: str,
        event_ids: Sequence[str],
        worker_id: str,
        error_message: str,
        *,
        retry_delay_seconds: int | None = None,
    ) -> None:
        """Records delivery failure, schedules capped exponential (or explicit) backoff retry, or dead-letters as `FAILED`."""
        ...

    async def mark_dead_letter_batch(
        self,
        queue_name: str,
        event_ids: Sequence[str],
        worker_id: str,
        error_message: str,
    ) -> None:
        """Immediately transitions terminal/poison-pill messages to `FAILED` without burning remaining retries."""
        ...

    async def cleanup_processed(self, retention_days: int = 7) -> int:
        """Purges `PROCESSED` queue rows older than `retention_days` in chunked transactions."""
        ...
