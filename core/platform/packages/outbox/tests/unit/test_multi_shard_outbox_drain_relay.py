"""Unit tests for High-Speed MultiShardOutboxDrainRelay (Drain-Until-Empty, Zero Mocks)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from outbox.adapters.inbound.multi_shard_outbox_drain_relay import (
    MultiShardOutboxDrainRelay,
    ShardOutboxDrainPort,
)
from outbox.testing.fakes import FakeOutboxPublisher
from seedwork.events import EventEnvelope, EventProcessingLane


class FakeShardOutboxDrainRepository(ShardOutboxDrainPort):
    """In-memory multi-shard outbox fake tracking batch claims and single-query completions."""

    def __init__(self, shard_events: dict[str, list[EventEnvelope]]) -> None:
        self.shard_events = {k: list(v) for k, v in shard_events.items()}
        self.completed_batches: list[tuple[str, tuple[str, ...], str]] = []
        self.failed_batches: list[tuple[str, tuple[str, ...], str, str]] = []
        self.claim_calls_per_shard: dict[str, int] = {k: 0 for k in shard_events}

    async def list_shards(self) -> list[tuple[str, str]]:
        return [(name, f"postgresql://{name}") for name in self.shard_events]

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
    ) -> None:
        self.failed_batches.append((shard_name, tuple(event_ids), worker_id, error_message))


def _evt(event_id: str, lane: EventProcessingLane = EventProcessingLane.REALTIME) -> EventEnvelope:
    return EventEnvelope(
        id=event_id,
        source="ip.data_plane",
        event_type="ip.inbound_record.created",
        tenant_id="tenant_1",
        idempotency_key=f"ik_{event_id}",
        payload={"record_ids": [f"rec_{event_id}"]},
        trace_id=f"trc_{event_id}",
        lane=lane,
    )


@pytest.mark.asyncio
async def test_multi_shard_outbox_drain_relay_drains_until_empty_with_bulk_completion() -> None:
    shard_1_events = [_evt(f"s1_{i}") for i in range(5)]
    shard_2_events = [_evt(f"s2_{i}", EventProcessingLane.BULK) for i in range(3)]

    repo = FakeShardOutboxDrainRepository(
        {
            "ip_shard_1": shard_1_events,
            "ip_shard_2": shard_2_events,
        }
    )
    publisher = FakeOutboxPublisher()

    relay = MultiShardOutboxDrainRelay(
        repository=repo,
        publisher=publisher,
        batch_size=2,
        shard_concurrency=2,
        poll_interval_seconds=0.05,
        worker_id="drain_worker_1",
    )

    total_published = await relay.drain_all_shards_once()
    assert total_published == 8
    assert len(publisher.published_events) == 8

    # Shard 1 had 5 events with batch_size=2 -> 3 non-empty claims (2, 2, 1) + 1 empty check = 4 claims
    assert repo.claim_calls_per_shard["ip_shard_1"] == 4
    # Shard 2 had 3 events with batch_size=2 -> 2 non-empty claims (2, 1) + 1 empty check = 3 claims
    assert repo.claim_calls_per_shard["ip_shard_2"] == 3

    # Verify mark_shard_completed_batch was called per batch (not per individual event!)
    s1_batches = [b[1] for b in repo.completed_batches if b[0] == "ip_shard_1"]
    assert s1_batches == [("s1_0", "s1_1"), ("s1_2", "s1_3"), ("s1_4",)]


@pytest.mark.asyncio
async def test_multi_shard_outbox_drain_relay_start_and_stop_lifecycle() -> None:
    repo = FakeShardOutboxDrainRepository({"ip_shard_1": [_evt("s1_0")]})
    publisher = FakeOutboxPublisher()
    relay = MultiShardOutboxDrainRelay(
        repository=repo,
        publisher=publisher,
        batch_size=10,
        poll_interval_seconds=0.02,
    )

    relay.start()
    assert len(relay.background_tasks()) == 1
    await asyncio.sleep(0.05)
    await relay.stop()

    assert len(publisher.published_events) == 1
    assert repo.shard_events["ip_shard_1"] == []
