"""Unit tests for OutboxDrainRelay and stateless SqlAlchemyShardedOutboxRepository."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from contextlib import AbstractAsyncContextManager

import pytest
from database.models.common import OutboxMixin
from database.router import DatabaseRouterPort
from database.types import GlobalSession, TenantSession
from outbox.adapters.inbound.outbox_drain_relay import OutboxDrainRelay
from outbox.adapters.outbound.sqlalchemy_sharded_outbox_repository import (
    SqlAlchemyShardedOutboxRepository,
)
from outbox.application.outbox_processor_use_case import (
    OutboxBatchResult,
    OutboxProcessorUseCase,
)
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from seedwork.events import EventEnvelope
from sqlalchemy.orm import DeclarativeBase


class _TestBase(DeclarativeBase):
    pass


class _DummyOutboxModel(_TestBase, OutboxMixin):
    __tablename__ = "dummy_outbox"


def _make_envelope(event_id: str) -> EventEnvelope:
    return EventEnvelope(
        id=event_id,
        source="test.control_plane",
        event_type="test.event",
        tenant_id="t_01",
        idempotency_key=f"idem_{event_id}",
        payload={"seq": event_id},
    )


class _QueuedOutboxRepo(OutboxRepositoryPort):
    """In-memory OutboxRepositoryPort fake supporting queued batches and injected failures."""

    def __init__(
        self,
        batches: Sequence[list[EventEnvelope] | Exception] = (),
    ) -> None:
        self._batches: list[list[EventEnvelope] | Exception] = list(batches)
        self.claim_calls = 0
        self.completed_ids: list[str] = []
        self.failed_ids: list[str] = []

    def enqueue_batch(self, events: list[EventEnvelope]) -> None:
        self._batches.append(events)

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[EventEnvelope]:
        del worker_id, limit, lock_lease_ms
        self.claim_calls += 1
        if not self._batches:
            return []
        next_item = self._batches.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    async def sweep_stuck_events(self, lock_lease_ms: int) -> int:
        del lock_lease_ms
        return 0

    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        del worker_id
        self.completed_ids.append(event_id)

    async def mark_completed_batch(self, event_ids: Sequence[str], worker_id: str) -> None:
        del worker_id
        self.completed_ids.extend(event_ids)

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
        del worker_id, error_message
        self.failed_ids.append(event_id)

    async def mark_failed_batch(
        self, event_ids: Sequence[str], worker_id: str, error_message: str
    ) -> None:
        del worker_id, error_message
        self.failed_ids.extend(event_ids)


class _RecordingPublisher(OutboxPublisherPort):
    def __init__(self, *, fail_next_batches: int = 0) -> None:
        self.published_ids: list[str] = []
        self.fail_next_batches = fail_next_batches

    async def publish(self, event: EventEnvelope) -> None:
        self.published_ids.append(event.id)

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        if self.fail_next_batches > 0:
            self.fail_next_batches -= 1
            raise RuntimeError("broker temporarily unavailable")
        ids = [event.id for event in events]
        self.published_ids.extend(ids)
        return ids


class _PartialBatchPublisher(OutboxPublisherPort):
    """Acknowledges only the first event in its first batch, then acknowledges everything."""

    def __init__(self) -> None:
        self.published_ids: list[str] = []
        self._did_partial = False

    async def publish(self, event: EventEnvelope) -> None:
        self.published_ids.append(event.id)

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        if not self._did_partial and len(events) > 1:
            self._did_partial = True
            ids = [events[0].id]
            self.published_ids.extend(ids)
            return ids
        ids = [event.id for event in events]
        self.published_ids.extend(ids)
        return ids


class _RecordingShardedRepo(SqlAlchemyShardedOutboxRepository[_DummyOutboxModel]):
    def __init__(self, router: DatabaseRouterPort) -> None:
        super().__init__(
            router,
            model_cls=_DummyOutboxModel,
            app_slug="edi",
            source="edi",
        )
        self.completed_calls: list[tuple[str, str, tuple[str, ...], str]] = []
        self.failed_calls: list[tuple[str, str, tuple[str, ...], str, str]] = []

    async def mark_shard_completed_batch(
        self,
        *,
        shard_name: str,
        shard_dsn: str,
        event_ids: Sequence[str],
        worker_id: str,
    ) -> None:
        self.completed_calls.append((shard_name, shard_dsn, tuple(event_ids), worker_id))

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
        self.failed_calls.append(
            (shard_name, shard_dsn, tuple(event_ids), worker_id, error_message)
        )
        return []


class _StubRouter(DatabaseRouterPort):
    def get_global_session(self) -> AsyncGenerator[GlobalSession, None]:
        raise NotImplementedError

    def global_session_scope(self) -> AbstractAsyncContextManager[GlobalSession]:
        raise NotImplementedError

    def get_tenant_session(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        raise NotImplementedError

    def get_shard_session(
        self, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        raise NotImplementedError

    async def get_all_shards(self, app_slug: str | None = None) -> list[tuple[str, str]]:
        assert app_slug == "edi"
        return [("edi_shard_1", "dsn://s1"), ("edi_shard_2", "dsn://s2")]

    async def close_all(self) -> None:
        return None


class _RecordingWaitRelay(OutboxDrainRelay):
    """Subclass capturing idle/error wait durations without slowing tests down."""

    def __init__(
        self,
        processor: OutboxProcessorUseCase,
        *,
        relay_name: str = "test",
        poll_interval_seconds: float = 0.25,
        max_idle_poll_interval_seconds: float = 1.0,
        error_backoff_seconds: float = 5.0,
    ) -> None:
        super().__init__(
            processor,
            relay_name=relay_name,
            poll_interval_seconds=poll_interval_seconds,
            max_idle_poll_interval_seconds=max_idle_poll_interval_seconds,
            error_backoff_seconds=error_backoff_seconds,
        )
        self.recorded_waits: list[float] = []
        self._wait_recorded = asyncio.Event()

    async def _wait_or_stop(self, timeout_seconds: float) -> None:
        self.recorded_waits.append(timeout_seconds)
        self._wait_recorded.set()
        await asyncio.sleep(0.005)


def test_outbox_drain_relay_validates_interval_parameters() -> None:
    repo = _QueuedOutboxRepo()
    processor = OutboxProcessorUseCase(repository=repo, publisher=_RecordingPublisher())

    with pytest.raises(ValueError, match="poll_interval_seconds"):
        OutboxDrainRelay(processor, poll_interval_seconds=0.0)

    with pytest.raises(ValueError, match="max_idle_poll_interval_seconds"):
        OutboxDrainRelay(
            processor,
            poll_interval_seconds=0.5,
            max_idle_poll_interval_seconds=0.25,
        )

    with pytest.raises(ValueError, match="error_backoff_seconds"):
        OutboxDrainRelay(processor, error_backoff_seconds=-1.0)


@pytest.mark.asyncio
async def test_outbox_drain_relay_drains_full_batches_back_to_back() -> None:
    repo = _QueuedOutboxRepo(
        batches=[
            [_make_envelope("e1"), _make_envelope("e2")],
            [_make_envelope("e3"), _make_envelope("e4")],
            [_make_envelope("e5")],
        ]
    )
    publisher = _RecordingPublisher()
    processor = OutboxProcessorUseCase(
        repository=repo,
        publisher=publisher,
        max_concurrent_events=2,
    )
    relay = OutboxDrainRelay(processor=processor, relay_name="identity")

    result = await relay.drain_until_empty()

    assert result == OutboxBatchResult(
        claimed_count=5,
        completed_count=5,
        failed_count=0,
        has_more=False,
    )
    assert repo.claim_calls == 3
    assert publisher.published_ids == ["e1", "e2", "e3", "e4", "e5"]
    assert repo.completed_ids == ["e1", "e2", "e3", "e4", "e5"]


@pytest.mark.asyncio
async def test_outbox_drain_relay_breaks_on_broker_failure_and_backs_off() -> None:
    """A full-batch publish failure stops 0ms draining immediately and backs off."""
    repo = _QueuedOutboxRepo(
        batches=[
            [_make_envelope("f1"), _make_envelope("f2")],
            [_make_envelope("ok1"), _make_envelope("ok2")],
        ]
    )
    publisher = _RecordingPublisher(fail_next_batches=1)
    processor = OutboxProcessorUseCase(
        repository=repo,
        publisher=publisher,
        max_concurrent_events=2,
    )
    relay = _RecordingWaitRelay(
        processor=processor,
        relay_name="edi_control_plane",
        poll_interval_seconds=0.25,
        max_idle_poll_interval_seconds=1.0,
        error_backoff_seconds=5.0,
    )

    # First standalone drain cycle must stop after batch 1 without touching batch 2.
    first_cycle = await relay.drain_until_empty()
    assert first_cycle == OutboxBatchResult(
        claimed_count=2,
        completed_count=0,
        failed_count=2,
        has_more=True,
    )
    assert repo.claim_calls == 1
    assert repo.failed_ids == ["f1", "f2"]
    assert publisher.published_ids == []

    # Now verify _run_loop applies error_backoff_seconds on full batch failure, then drains ok batch.
    repo2 = _QueuedOutboxRepo(
        batches=[
            [_make_envelope("f3"), _make_envelope("f4")],
            [_make_envelope("ok3")],
        ]
    )
    pub2 = _RecordingPublisher(fail_next_batches=1)
    relay2 = _RecordingWaitRelay(
        processor=OutboxProcessorUseCase(repository=repo2, publisher=pub2, max_concurrent_events=2),
        relay_name="edi_control_plane",
        poll_interval_seconds=0.25,
        max_idle_poll_interval_seconds=1.0,
        error_backoff_seconds=5.0,
    )
    relay2.start()
    try:
        while not pub2.published_ids:
            relay2._wait_recorded.clear()
            await asyncio.wait_for(relay2._wait_recorded.wait(), timeout=1.0)

        assert relay2.recorded_waits[0] == 5.0
        assert pub2.published_ids == ["ok3"]
    finally:
        await relay2.stop()


@pytest.mark.asyncio
async def test_outbox_drain_relay_partial_batch_failure_breaks_tight_loop_and_uses_poll_interval() -> (
    None
):
    """A partial batch failure stops 0ms draining without triggering full error_backoff_seconds."""
    repo = _QueuedOutboxRepo(
        batches=[
            [_make_envelope("p1"), _make_envelope("p2")],
            [_make_envelope("p3")],
        ]
    )
    publisher = _PartialBatchPublisher()
    relay = OutboxDrainRelay(
        processor=OutboxProcessorUseCase(
            repository=repo,
            publisher=publisher,
            max_concurrent_events=2,
        ),
        relay_name="edi_control_plane",
        poll_interval_seconds=0.25,
        max_idle_poll_interval_seconds=1.0,
        error_backoff_seconds=5.0,
    )

    first_cycle = await relay.drain_until_empty()
    assert first_cycle == OutboxBatchResult(
        claimed_count=2,
        completed_count=1,
        failed_count=1,
        has_more=True,
    )
    assert repo.claim_calls == 1
    assert repo.completed_ids == ["p1"]
    assert repo.failed_ids == ["p2"]

    # In _run_loop, partial failure sleeps poll_interval_seconds (0.25s), NOT error_backoff_seconds (5.0s).
    repo2 = _QueuedOutboxRepo(
        batches=[
            [_make_envelope("p4"), _make_envelope("p5")],
            [_make_envelope("p6")],
        ]
    )
    pub2 = _PartialBatchPublisher()
    relay2 = _RecordingWaitRelay(
        processor=OutboxProcessorUseCase(repository=repo2, publisher=pub2, max_concurrent_events=2),
        relay_name="edi_control_plane",
        poll_interval_seconds=0.25,
        max_idle_poll_interval_seconds=1.0,
        error_backoff_seconds=5.0,
    )
    relay2.start()
    try:
        while "p6" not in pub2.published_ids:
            relay2._wait_recorded.clear()
            await asyncio.wait_for(relay2._wait_recorded.wait(), timeout=1.0)

        assert relay2.recorded_waits[0] == 0.25
        assert 5.0 not in relay2.recorded_waits
        assert pub2.published_ids == ["p4", "p6"]
    finally:
        await relay2.stop()


@pytest.mark.asyncio
async def test_outbox_drain_relay_adaptive_backoff_resets_on_single_event() -> None:
    """Even a partial batch (1 event < max_concurrent_events) resets idle backoff to 0.25s."""
    repo = _QueuedOutboxRepo()
    publisher = _RecordingPublisher()
    processor = OutboxProcessorUseCase(
        repository=repo,
        publisher=publisher,
        max_concurrent_events=50,
    )
    relay = _RecordingWaitRelay(
        processor=processor,
        relay_name="ucp",
        poll_interval_seconds=0.25,
        max_idle_poll_interval_seconds=1.0,
    )

    relay.start()
    try:
        while len(relay.recorded_waits) < 4:
            relay._wait_recorded.clear()
            await asyncio.wait_for(relay._wait_recorded.wait(), timeout=1.0)

        assert relay.recorded_waits[:4] == [0.25, 0.5, 1.0, 1.0]

        # Enqueue a single event (far below max_concurrent_events=50); backoff must reset to 0.25s.
        repo.enqueue_batch([_make_envelope("single_1")])
        waits_before_event = len(relay.recorded_waits)
        while len(relay.recorded_waits) <= waits_before_event + 1:
            relay._wait_recorded.clear()
            await asyncio.wait_for(relay._wait_recorded.wait(), timeout=1.0)

        assert publisher.published_ids == ["single_1"]
        assert 0.25 in relay.recorded_waits[waits_before_event:]
    finally:
        await relay.stop()

    assert relay.is_running is False
    assert relay.background_tasks() == []


@pytest.mark.asyncio
async def test_outbox_drain_relay_recovers_from_error_and_stops_immediately() -> None:
    repo = _QueuedOutboxRepo(
        batches=[
            RuntimeError("transient connection reset"),
            [_make_envelope("e_after_err")],
        ]
    )
    publisher = _RecordingPublisher()
    processor = OutboxProcessorUseCase(
        repository=repo,
        publisher=publisher,
        max_concurrent_events=10,
    )
    relay = _RecordingWaitRelay(
        processor=processor,
        relay_name="notification",
        poll_interval_seconds=0.25,
        max_idle_poll_interval_seconds=1.0,
        error_backoff_seconds=5.0,
    )

    relay.start()
    try:
        while not publisher.published_ids:
            relay._wait_recorded.clear()
            await asyncio.wait_for(relay._wait_recorded.wait(), timeout=1.0)

        assert relay.recorded_waits[0] == 5.0
        assert publisher.published_ids == ["e_after_err"]
    finally:
        await relay.stop()

    # Also verify a real OutboxDrainRelay wakes up immediately on stop() during a long idle sleep.
    idle_relay = OutboxDrainRelay(
        processor=OutboxProcessorUseCase(
            repository=_QueuedOutboxRepo(),
            publisher=_RecordingPublisher(),
        ),
        relay_name="edi_control_plane",
        poll_interval_seconds=30.0,
        max_idle_poll_interval_seconds=30.0,
    )
    idle_relay.start()
    await asyncio.sleep(0.02)
    assert len(idle_relay.background_tasks()) == 1
    await asyncio.wait_for(idle_relay.stop(), timeout=0.5)
    assert idle_relay.background_tasks() == []


@pytest.mark.asyncio
async def test_sharded_outbox_repository_is_stateless_and_fans_out_batches() -> None:
    repo = _RecordingShardedRepo(_StubRouter())
    assert not hasattr(repo, "_event_shard_map")

    await repo.mark_completed_batch(["evt_1", "evt_2"], "worker_a")
    assert sorted(repo.completed_calls) == [
        ("edi_shard_1", "dsn://s1", ("evt_1", "evt_2"), "worker_a"),
        ("edi_shard_2", "dsn://s2", ("evt_1", "evt_2"), "worker_a"),
    ]

    await repo.mark_failed_batch(["evt_3"], "worker_a", "boom")
    assert sorted(repo.failed_calls) == [
        ("edi_shard_1", "dsn://s1", ("evt_3",), "worker_a", "boom"),
        ("edi_shard_2", "dsn://s2", ("evt_3",), "worker_a", "boom"),
    ]
