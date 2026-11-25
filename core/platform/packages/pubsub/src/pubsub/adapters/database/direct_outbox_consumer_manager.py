"""Sovereign Single-Queue PostgreSQL Consumer Manager implementing ConsumerManagerPort."""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, cast, runtime_checkable

import structlog
from outbox.ports.outbox_relay_port import OutboxRelayPort
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from pubsub.domain.dtos import EventDispatchOutcome, TopicSubscriptionSpec
from pubsub.domain.enums import normalize_database_queue_name, normalize_database_topic_name
from pubsub.enums import ConsumerAction
from pubsub.ports.consumer_manager_port import ConsumerManagerPort
from pubsub.ports.database_queue_port import DatabaseQueuePort, DirectBatchDispatcherPort

logger = structlog.get_logger(__name__)


@runtime_checkable
class GlobalOutboxProcessorPort(Protocol):
    """Minimal protocol for draining a Global DB outbox repository."""

    async def process_pending(self) -> bool: ...

    def stop(self) -> None: ...


@runtime_checkable
class ShardDrainRelayPort(OutboxRelayPort, Protocol):
    """Extension of OutboxRelayPort supporting deterministic single-cycle draining."""

    is_running: bool

    async def drain_all_shards_once(self) -> int: ...


class DirectOutboxConsumerManager(ConsumerManagerPort):
    """Autonomous consumer pump draining PostgreSQL Outbox or Platform Queue tables (`FOR UPDATE SKIP LOCKED`).

    Depends strictly on abstract Ports assembled by the Composition Root (`PubSubProvider`).
    Features adaptive idle backoff (0ms drain-until-empty when busy, exponential idle sleep up to
    `max_idle_sleep_seconds` when empty), full ACK/NACK(retry_delay)/DLQ routing, and clean
    disposal of any owned fallback database engine on `stop()`.
    """

    def __init__(
        self,
        source_uri: str,
        *,
        direct_publisher: DirectBatchDispatcherPort,
        shard_relay: ShardDrainRelayPort | None = None,
        global_processor: GlobalOutboxProcessorPort | None = None,
        database_queue: DatabaseQueuePort | None = None,
        topic_subscriptions: Sequence[TopicSubscriptionSpec] = (),
        batch_size: int = 500,
        lock_lease_ms: int = 30000,
        poll_sleep_seconds: float = 0.1,
        max_idle_sleep_seconds: float = 1.0,
        worker_id: str | None = None,
        owned_db_close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if shard_relay is None and global_processor is None and database_queue is None:
            raise ValueError(
                "DirectOutboxConsumerManager requires one of shard_relay, global_processor, or database_queue."
            )
        self.source_uri = source_uri
        self.queue_name = normalize_database_queue_name(source_uri)
        self.direct_publisher = direct_publisher
        self._shard_relay = shard_relay
        self._global_processor = global_processor
        self._database_queue = database_queue
        self._topic_subscriptions: tuple[TopicSubscriptionSpec, ...] = tuple(topic_subscriptions)
        self._subscriptions_registered: bool = False
        self.batch_size = batch_size
        self.lock_lease_ms = lock_lease_ms
        self.poll_sleep_seconds = poll_sleep_seconds
        self.max_idle_sleep_seconds = max(poll_sleep_seconds, max_idle_sleep_seconds)
        self.worker_id = worker_id or generate_id(SystemIdPrefix.GENERIC)
        self._owned_db_close = owned_db_close
        self.is_running: bool = False
        self._task: asyncio.Task[None] | None = None

    async def ensure_subscriptions(self) -> None:
        """Idempotently registers all consumer-declared topic subscriptions in `pubsub.platform_topic_subscriptions`."""
        if (
            self._subscriptions_registered
            or self._database_queue is None
            or not self._topic_subscriptions
        ):
            return
        for spec in self._topic_subscriptions:
            topic_name = normalize_database_topic_name(spec.topic_name)
            await self._database_queue.register_subscription(
                topic_name=topic_name,
                target_queue=self.queue_name,
                event_types=spec.event_types,
            )
        self._subscriptions_registered = True

    def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        if self._shard_relay is not None:
            self._shard_relay.start()
        else:
            self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "direct_outbox_consumer_manager_started",
            queue=self.queue_name,
            worker_id=self.worker_id,
        )

    async def stop(self) -> None:
        self.is_running = False
        if self._shard_relay is not None:
            await self._shard_relay.stop()
        if self._global_processor is not None:
            self._global_processor.stop()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._owned_db_close is not None:
            await self._owned_db_close()
            self._owned_db_close = None
        logger.info(
            "direct_outbox_consumer_manager_stopped",
            queue=self.queue_name,
            worker_id=self.worker_id,
        )

    async def health_check(self) -> bool:
        if not self.is_running:
            return False
        if self._shard_relay is not None:
            return self._shard_relay.is_running
        return self._task is None or not self._task.done()

    @property
    def task(self) -> asyncio.Task[None] | None:
        if self._shard_relay is not None:
            tasks = self._shard_relay.background_tasks()
            return cast(asyncio.Task[None], tasks[0]) if tasks else None
        return self._task

    def background_tasks(self) -> list[asyncio.Task[object]]:
        if self._shard_relay is not None:
            return self._shard_relay.background_tasks()
        if self._task is not None:
            return [self._task]
        return []

    async def drain_once(self) -> int:
        """Executes a single drain cycle against the injected PostgreSQL outbox or queue port."""
        if self._shard_relay is not None:
            return await self._shard_relay.drain_all_shards_once()

        if self._global_processor is not None:
            cycles = 0
            while await self._global_processor.process_pending():
                cycles += 1
            return cycles

        if self._database_queue is None:
            return 0

        claimed = await self._database_queue.claim_batch(
            queue_name=self.queue_name,
            worker_id=self.worker_id,
            limit=self.batch_size,
            lock_lease_ms=self.lock_lease_ms,
        )
        if not claimed:
            return 0

        try:
            outcomes = await self.direct_publisher.dispatch_batch_outcomes(claimed)
        except Exception as exc:
            logger.exception(
                "database_queue_batch_dispatch_failed",
                queue=self.queue_name,
                worker_id=self.worker_id,
                error=str(exc),
            )
            await self._database_queue.mark_failed_batch(
                queue_name=self.queue_name,
                event_ids=[e.id for e in claimed],
                worker_id=self.worker_id,
                error_message=str(exc) or type(exc).__name__,
            )
            return 0

        return await self._apply_database_queue_outcomes(self._database_queue, outcomes)

    async def _apply_database_queue_outcomes(
        self,
        database_queue: DatabaseQueuePort,
        outcomes: Sequence[EventDispatchOutcome],
    ) -> int:
        completed_ids: list[str] = []
        dlq_by_reason: dict[str, list[str]] = defaultdict(list)
        nack_groups: dict[tuple[int | None, str], list[str]] = defaultdict(list)

        for outcome in outcomes:
            if outcome.action == ConsumerAction.ACK:
                completed_ids.append(outcome.event_id)
            elif outcome.action == ConsumerAction.DLQ:
                reason = outcome.error_message or "Dead-lettered by consumer"
                dlq_by_reason[reason].append(outcome.event_id)
            else:
                reason = outcome.error_message or "Handler NACKed or failed to process message"
                nack_groups[(outcome.retry_delay_seconds, reason)].append(outcome.event_id)

        if completed_ids:
            await database_queue.mark_completed_batch(
                queue_name=self.queue_name,
                event_ids=completed_ids,
                worker_id=self.worker_id,
            )

        for reason, event_ids in dlq_by_reason.items():
            await database_queue.mark_dead_letter_batch(
                queue_name=self.queue_name,
                event_ids=event_ids,
                worker_id=self.worker_id,
                error_message=reason,
            )
            logger.error(
                "database_queue_batch_dead_lettered",
                queue=self.queue_name,
                worker_id=self.worker_id,
                dlq_count=len(event_ids),
                reason=reason,
            )

        for (retry_delay, reason), event_ids in nack_groups.items():
            await database_queue.mark_failed_batch(
                queue_name=self.queue_name,
                event_ids=event_ids,
                worker_id=self.worker_id,
                error_message=reason,
                retry_delay_seconds=retry_delay,
            )
            logger.error(
                "database_queue_batch_marked_failed",
                queue=self.queue_name,
                worker_id=self.worker_id,
                failed_count=len(event_ids),
                retry_delay_seconds=retry_delay,
            )

        return len(completed_ids) + sum(len(ids) for ids in dlq_by_reason.values())

    async def _run_loop(self) -> None:
        idle_sleep = self.poll_sleep_seconds
        while self.is_running:
            try:
                await self.ensure_subscriptions()
                count = await self.drain_once()
                if count > 0:
                    # Busy: drain-until-empty with 0ms sleep and reset idle backoff
                    idle_sleep = self.poll_sleep_seconds
                elif self.is_running:
                    await asyncio.sleep(idle_sleep)
                    idle_sleep = min(self.max_idle_sleep_seconds, idle_sleep * 2.0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(
                    "direct_outbox_consumer_loop_error",
                    queue=self.queue_name,
                    worker_id=self.worker_id,
                    error=str(exc),
                )
                await asyncio.sleep(1.0)
