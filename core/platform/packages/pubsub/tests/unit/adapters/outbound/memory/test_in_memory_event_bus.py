"""
Unit tests for InMemoryEventBus.

InMemoryEventBus must satisfy two port contracts simultaneously:
  - OutboxPublisherPort  (publish / publish_batch accepting list[EventEnvelope])
  - MessageConsumerPort  (async context manager + poll_raw_message)

Tests use real EventEnvelope instances to validate type-correct port usage —
the same way production code and mypy will see it.
"""

from __future__ import annotations

import asyncio

import pytest
from pubsub.message import AckableMessage
from pubsub.ports.message_consumer_port import MessageConsumerPort
from pubsub.testing.in_memory_event_bus import InMemoryEventBus
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id


def _make_event(event_type: str = "order.created", index: int = 1) -> EventEnvelope:
    return EventEnvelope(
        id=generate_id(SystemIdPrefix.EVENT.value),
        source="test-service",
        event_type=event_type,
        tenant_id=generate_id("iam_ten"),
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY.value),
        payload={"index": index},
    )


@pytest.mark.asyncio
async def test_publish_batch_enqueues_all_events_and_returns_ids() -> None:
    bus = InMemoryEventBus()
    events = [_make_event(index=1), _make_event(index=2)]

    successful_ids = await bus.publish_batch(events)

    assert successful_ids == [events[0].id, events[1].id]
    assert bus.queue.qsize() == 2


@pytest.mark.asyncio
async def test_publish_batch_stores_dict_representation_of_envelope() -> None:
    bus = InMemoryEventBus()
    event = _make_event(event_type="shipment.dispatched", index=3)

    await bus.publish_batch([event])

    enqueued = bus.queue.get_nowait()
    assert enqueued == event.to_dict()
    assert enqueued["event_type"] == "shipment.dispatched"
    assert enqueued["payload"] == {"index": 3}


@pytest.mark.asyncio
async def test_publish_batch_with_empty_list_returns_empty_and_leaves_queue_empty() -> None:
    bus = InMemoryEventBus()
    result = await bus.publish_batch([])
    assert result == []
    assert bus.queue.empty()


@pytest.mark.asyncio
async def test_publish_single_enqueues_dict_representation() -> None:
    bus = InMemoryEventBus()
    event = _make_event(event_type="user.registered", index=4)

    await bus.publish(event)

    assert bus.queue.qsize() == 1
    enqueued = bus.queue.get_nowait()
    assert enqueued == event.to_dict()


@pytest.mark.asyncio
async def test_context_manager_returns_same_bus_instance() -> None:
    bus = InMemoryEventBus()
    async with bus as entered:
        assert entered is bus


@pytest.mark.asyncio
async def test_poll_raw_message_yields_none_when_queue_is_empty() -> None:
    bus = InMemoryEventBus()
    async with bus.poll_raw_message() as msg:
        assert msg is None


@pytest.mark.asyncio
async def test_poll_raw_message_yields_ackable_message_with_correct_payload() -> None:
    bus = InMemoryEventBus()
    event = _make_event(event_type="invoice.paid", index=5)
    await bus.publish_batch([event])

    async with bus.poll_raw_message() as msg:
        assert isinstance(msg, AckableMessage)
        assert isinstance(msg.payload, dict)
        assert msg.payload == event.to_dict()


@pytest.mark.asyncio
async def test_ack_marks_task_done_so_queue_join_does_not_block() -> None:
    bus = InMemoryEventBus()
    await bus.publish_batch([_make_event(index=6)])

    async with bus.poll_raw_message() as msg:
        assert msg is not None
        await msg.ack()

    await bus.queue.join()


@pytest.mark.asyncio
async def test_nack_reenqueues_the_message_for_redelivery() -> None:
    bus = InMemoryEventBus()
    event = _make_event(event_type="payment.failed", index=7)
    await bus.publish_batch([event])

    async with bus.poll_raw_message() as msg:
        assert msg is not None
        await msg.nack()

    assert bus.queue.qsize() == 1
    requeued = bus.queue.get_nowait()
    assert requeued == event.to_dict()


@pytest.mark.asyncio
async def test_consumer_error_reenqueues_unacknowledged_message() -> None:
    bus = InMemoryEventBus()
    event = _make_event(event_type="payment.failed", index=9)
    await bus.publish_batch([event])

    with pytest.raises(RuntimeError, match="handler failed"):
        async with bus.poll_raw_message():
            raise RuntimeError("handler failed")

    assert bus.queue.qsize() == 1
    assert bus.queue.get_nowait() == event.to_dict()
    bus.queue.task_done()
    await asyncio.wait_for(bus.queue.join(), timeout=0.1)


@pytest.mark.asyncio
async def test_consumer_error_does_not_requeue_acknowledged_message() -> None:
    bus = InMemoryEventBus()
    await bus.publish_batch([_make_event(index=10)])

    with pytest.raises(RuntimeError, match="post-ack failure"):
        async with bus.poll_raw_message() as msg:
            assert msg is not None
            await msg.ack()
            raise RuntimeError("post-ack failure")

    assert bus.queue.empty()


@pytest.mark.asyncio
async def test_normal_exit_reenqueues_unacknowledged_message() -> None:
    bus = InMemoryEventBus()
    event = _make_event(event_type="payment.pending", index=11)
    await bus.publish_batch([event])

    async with bus.poll_raw_message() as msg:
        assert msg is not None

    assert bus.queue.qsize() == 1
    assert bus.queue.get_nowait() == event.to_dict()
    bus.queue.task_done()
    await asyncio.wait_for(bus.queue.join(), timeout=0.1)


@pytest.mark.asyncio
async def test_clear_drains_all_enqueued_messages() -> None:
    bus = InMemoryEventBus()
    events = [_make_event(index=i) for i in range(5)]
    await bus.publish_batch(events)
    assert bus.queue.qsize() == 5

    await bus.clear()

    assert bus.queue.empty()


@pytest.mark.asyncio
async def test_clear_is_idempotent_on_empty_queue() -> None:
    bus = InMemoryEventBus()
    await bus.clear()
    assert bus.queue.empty()


@pytest.mark.asyncio
async def test_full_round_trip_publish_poll_ack() -> None:
    bus = InMemoryEventBus()
    event = _make_event(event_type="shipment.dispatched", index=8)

    await bus.publish_batch([event])

    received_payload: JsonDict | None = None
    async with bus.poll_raw_message() as msg:
        assert msg is not None
        received_payload = msg.payload
        await msg.ack()

    assert received_payload is not None
    assert isinstance(received_payload, dict)
    assert received_payload == event.to_dict()
    assert bus.queue.empty()


def test_in_memory_event_bus_satisfies_message_consumer_port_protocol() -> None:
    bus = InMemoryEventBus()
    assert isinstance(bus, MessageConsumerPort)


@pytest.mark.asyncio
async def test_publish_and_publish_batch_snapshot_nested_payloads() -> None:
    bus = InMemoryEventBus()
    single_payload: JsonDict = {"nested": {"status": "new"}, "tags": ["a"]}
    batch_payload: JsonDict = {"nested": {"count": 1}, "tags": ["b"]}

    single_event = EventEnvelope(
        id=generate_id(SystemIdPrefix.EVENT.value),
        source="test-service",
        event_type="order.updated",
        tenant_id=generate_id("iam_ten"),
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY.value),
        payload=single_payload,
    )
    batch_event = EventEnvelope(
        id=generate_id(SystemIdPrefix.EVENT.value),
        source="test-service",
        event_type="order.batched",
        tenant_id=generate_id("iam_ten"),
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY.value),
        payload=batch_payload,
    )

    await bus.publish(single_event)
    await bus.publish_batch([batch_event])

    # Mutate nested structures in-place after publishing
    assert isinstance(single_event.payload["nested"], dict)
    assert isinstance(single_event.payload["tags"], list)
    single_event.payload["nested"]["status"] = "mutated"
    single_event.payload["tags"].append("leaked")

    assert isinstance(batch_event.payload["nested"], dict)
    assert isinstance(batch_event.payload["tags"], list)
    batch_event.payload["nested"]["count"] = 999
    batch_event.payload["tags"].append("leaked")

    first = bus.queue.get_nowait()
    second = bus.queue.get_nowait()
    assert first["payload"] == {"nested": {"status": "new"}, "tags": ["a"]}
    assert second["payload"] == {"nested": {"count": 1}, "tags": ["b"]}


@pytest.mark.asyncio
async def test_nack_redelivers_unmutated_payload_when_consumer_mutates_in_place() -> None:
    bus = InMemoryEventBus()
    event = EventEnvelope(
        id=generate_id(SystemIdPrefix.EVENT.value),
        source="test-service",
        event_type="order.updated",
        tenant_id=generate_id("iam_ten"),
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY.value),
        payload={"nested": {"attempt": 0}},
    )
    await bus.publish(event)

    async with bus.poll_raw_message() as msg:
        assert msg is not None
        inner_payload = msg.payload["payload"]
        assert isinstance(inner_payload, dict)
        nested = inner_payload["nested"]
        assert isinstance(nested, dict)
        nested["attempt"] = 99
        await msg.nack()

    async with bus.poll_raw_message() as redelivered:
        assert redelivered is not None
        assert redelivered.payload["payload"] == {"nested": {"attempt": 0}}
        await redelivered.ack()
