"""Unit tests for Lane-Aware EventTypeOutboxRouter (Zero Mocks)."""

from __future__ import annotations

import pytest
from outbox.adapters.outbound.event_type_router import EventTypeOutboxRouter
from outbox.testing.fakes import FakeOutboxPublisher
from seedwork.events import EventEnvelope, EventProcessingLane


def _make_envelope(
    event_id: str,
    event_type: str,
    lane: EventProcessingLane = EventProcessingLane.REALTIME,
) -> EventEnvelope:
    return EventEnvelope(
        id=event_id,
        source="ip.data_plane",
        event_type=event_type,
        tenant_id="tenant_1",
        idempotency_key=f"ik_{event_id}",
        payload={"record_ids": [f"rec_{event_id}"]},
        trace_id=f"trc_{event_id}",
        correlation_id="MTR-101",
        lane=lane,
    )


@pytest.mark.asyncio
async def test_event_type_router_routes_by_event_type_and_queue_lane() -> None:
    orch_rt = FakeOutboxPublisher()
    orch_bulk = FakeOutboxPublisher()
    deliv_rt = FakeOutboxPublisher()
    deliv_bulk = FakeOutboxPublisher()

    router = EventTypeOutboxRouter(
        routes={
            ("ip.inbound_record.created", EventProcessingLane.REALTIME): orch_rt,
            ("ip.inbound_record.created", EventProcessingLane.BULK): orch_bulk,
            ("ip.outbound_record.created", EventProcessingLane.REALTIME): deliv_rt,
            ("ip.outbound_record.created", EventProcessingLane.BULK): deliv_bulk,
        }
    )

    e1 = _make_envelope("e1", "ip.inbound_record.created", EventProcessingLane.REALTIME)
    e2 = _make_envelope("e2", "ip.inbound_record.created", EventProcessingLane.BULK)
    e3 = _make_envelope("e3", "ip.outbound_record.created", EventProcessingLane.REALTIME)
    e4 = _make_envelope("e4", "ip.outbound_record.created", EventProcessingLane.BULK)

    acked = await router.publish_batch([e1, e2, e3, e4])
    assert set(acked) == {"e1", "e2", "e3", "e4"}
    assert [e.id for e in orch_rt.published_events] == ["e1"]
    assert [e.id for e in orch_bulk.published_events] == ["e2"]
    assert [e.id for e in deliv_rt.published_events] == ["e3"]
    assert [e.id for e in deliv_bulk.published_events] == ["e4"]


@pytest.mark.asyncio
async def test_event_type_router_partial_failure_returns_successful_ids_only() -> None:
    orch_rt = FakeOutboxPublisher()
    deliv_rt = FakeOutboxPublisher()
    deliv_rt.fail_on_publish = True

    router = EventTypeOutboxRouter(
        routes={
            ("ip.inbound_record.created", EventProcessingLane.REALTIME): orch_rt,
            ("ip.outbound_record.created", EventProcessingLane.REALTIME): deliv_rt,
        }
    )

    e1 = _make_envelope("e1", "ip.inbound_record.created", EventProcessingLane.REALTIME)
    e2 = _make_envelope("e2", "ip.outbound_record.created", EventProcessingLane.REALTIME)

    acked = await router.publish_batch([e1, e2])
    assert acked == ["e1"]


@pytest.mark.asyncio
async def test_event_type_router_single_publish_and_fallback_lane() -> None:
    orch_rt = FakeOutboxPublisher()
    router = EventTypeOutboxRouter(
        routes={
            ("ip.replica_record.changed", EventProcessingLane.REALTIME): orch_rt,
        }
    )

    # Single publish on exact lane
    e1 = _make_envelope("e1", "ip.replica_record.changed", EventProcessingLane.REALTIME)
    await router.publish(e1)
    assert len(orch_rt.published_events) == 1

    # Fallback to REALTIME lane when BULK lane is not separately registered for that event_type
    e2 = _make_envelope("e2", "ip.replica_record.changed", EventProcessingLane.BULK)
    await router.publish(e2)
    assert len(orch_rt.published_events) == 2
