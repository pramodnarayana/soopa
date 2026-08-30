"""
Unit tests for InMemoryEventBus.

InMemoryEventBus must satisfy two port contracts simultaneously:
  - OutboxPublisherPort  (publish / publish_batch accepting list[EventEnvelope])
  - MessageConsumerPort  (async context manager + poll_raw_message)

Tests use real EventEnvelope instances to validate type-correct port usage —
the same way production code and mypy will see it.
"""

import asyncio
import dataclasses

import pytest
from database.events import EventEnvelope
from pubsub.message import AckableMessage
from pubsub.testing.in_memory_event_bus import InMemoryEventBus


def _make_event(event_type: str = "order.created", index: int = 1) -> EventEnvelope:
    return EventEnvelope(
        id=f"evt-{index}",
        source="test-service",
        event_type=event_type,
        tenant_id="t-1",
        idempotency_key=f"ikey-{index}",
        payload={"index": index},
    )


# ---------------------------------------------------------------------------
# OutboxPublisherPort — publish_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_batch_enqueues_all_events_and_returns_ids():
    bus = InMemoryEventBus()
    events = [_make_event(index=1), _make_event(index=2)]

    successful_ids = await bus.publish_batch(events)

    assert successful_ids == ["evt-1", "evt-2"]
    assert bus.queue.qsize() == 2


@pytest.mark.asyncio
async def test_publish_batch_stores_dict_representation_of_envelope():
    """Enqueued payload must be the dataclass-asdict form so consumers can deserialise it."""
    bus = InMemoryEventBus()
    event = _make_event(event_type="shipment.dispatched", index=3)

    await bus.publish_batch([event])

    enqueued = bus.queue.get_nowait()
    assert enqueued == dataclasses.asdict(event)


@pytest.mark.asyncio
async def test_publish_batch_with_empty_list_returns_empty_and_leaves_queue_empty():
    bus = InMemoryEventBus()
    result = await bus.publish_batch([])
    assert result == []
    assert bus.queue.empty()


# ---------------------------------------------------------------------------
# OutboxPublisherPort — publish (single)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_single_enqueues_dict_representation():
    bus = InMemoryEventBus()
    event = _make_event(event_type="user.registered", index=4)

    await bus.publish(event)

    assert bus.queue.qsize() == 1
    enqueued = bus.queue.get_nowait()
    assert enqueued == dataclasses.asdict(event)


# ---------------------------------------------------------------------------
# MessageConsumerPort — async context manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_manager_returns_same_bus_instance():
    bus = InMemoryEventBus()
    async with bus as entered:
        assert entered is bus


# ---------------------------------------------------------------------------
# MessageConsumerPort — poll_raw_message (empty queue)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_raw_message_yields_none_when_queue_is_empty():
    bus = InMemoryEventBus()
    async with bus.poll_raw_message() as msg:
        assert msg is None


# ---------------------------------------------------------------------------
# MessageConsumerPort — poll_raw_message (message available)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_raw_message_yields_ackable_message_with_correct_payload():
    bus = InMemoryEventBus()
    event = _make_event(event_type="invoice.paid", index=5)
    await bus.publish_batch([event])

    async with bus.poll_raw_message() as msg:
        assert isinstance(msg, AckableMessage)
        assert msg.payload == dataclasses.asdict(event)


# ---------------------------------------------------------------------------
# ack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ack_marks_task_done_so_queue_join_does_not_block():
    bus = InMemoryEventBus()
    await bus.publish_batch([_make_event(index=6)])

    async with bus.poll_raw_message() as msg:
        assert msg is not None
        await msg.ack()

    await bus.queue.join()  # would raise/block if task_done was not called


# ---------------------------------------------------------------------------
# nack — re-enqueue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nack_reenqueues_the_message_for_redelivery():
    bus = InMemoryEventBus()
    event = _make_event(event_type="payment.failed", index=7)
    await bus.publish_batch([event])

    async with bus.poll_raw_message() as msg:
        assert msg is not None
        await msg.nack()

    # Message must be back in the queue for redelivery (SQS visibility timeout simulation)
    assert bus.queue.qsize() == 1
    requeued = bus.queue.get_nowait()
    assert requeued == dataclasses.asdict(event)


@pytest.mark.asyncio
async def test_consumer_error_reenqueues_unacknowledged_message():
    bus = InMemoryEventBus()
    event = _make_event(event_type="payment.failed", index=9)
    await bus.publish_batch([event])

    with pytest.raises(RuntimeError, match="handler failed"):
        async with bus.poll_raw_message():
            raise RuntimeError("handler failed")

    assert bus.queue.qsize() == 1
    assert bus.queue.get_nowait() == dataclasses.asdict(event)
    bus.queue.task_done()
    await asyncio.wait_for(bus.queue.join(), timeout=0.1)


@pytest.mark.asyncio
async def test_consumer_error_does_not_requeue_acknowledged_message():
    bus = InMemoryEventBus()
    await bus.publish_batch([_make_event(index=10)])

    with pytest.raises(RuntimeError, match="post-ack failure"):
        async with bus.poll_raw_message() as msg:
            assert msg is not None
            await msg.ack()
            raise RuntimeError("post-ack failure")

    assert bus.queue.empty()


@pytest.mark.asyncio
async def test_normal_exit_reenqueues_unacknowledged_message():
    bus = InMemoryEventBus()
    event = _make_event(event_type="payment.pending", index=11)
    await bus.publish_batch([event])

    async with bus.poll_raw_message() as msg:
        assert msg is not None

    assert bus.queue.qsize() == 1
    assert bus.queue.get_nowait() == dataclasses.asdict(event)
    bus.queue.task_done()
    await asyncio.wait_for(bus.queue.join(), timeout=0.1)


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_drains_all_enqueued_messages():
    bus = InMemoryEventBus()
    events = [_make_event(index=i) for i in range(5)]
    await bus.publish_batch(events)
    assert bus.queue.qsize() == 5

    await bus.clear()

    assert bus.queue.empty()


@pytest.mark.asyncio
async def test_clear_is_idempotent_on_empty_queue():
    bus = InMemoryEventBus()
    await bus.clear()
    assert bus.queue.empty()


# ---------------------------------------------------------------------------
# Full round-trip: publish → poll → ack (simulates outbox-to-consumer pipeline)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_round_trip_publish_poll_ack():
    """
    Verifies the complete in-memory simulation of the SQS/SNS pipeline:
    OutboxPublisherPort.publish_batch → MessageConsumerPort.poll_raw_message → ack.
    """
    bus = InMemoryEventBus()
    event = _make_event(event_type="shipment.dispatched", index=8)

    await bus.publish_batch([event])

    received_payload: dict | None = None
    async with bus.poll_raw_message() as msg:
        assert msg is not None
        received_payload = msg.payload
        await msg.ack()

    assert received_payload == dataclasses.asdict(event)
    assert bus.queue.empty()


# ---------------------------------------------------------------------------
# Port conformance: runtime_checkable Protocol structural check
# ---------------------------------------------------------------------------


def test_in_memory_event_bus_satisfies_message_consumer_port_protocol():
    """Structural isinstance check ensures InMemoryEventBus conforms to MessageConsumerPort."""
    from pubsub.ports.message_consumer_port import MessageConsumerPort

    bus = InMemoryEventBus()
    assert isinstance(bus, MessageConsumerPort)
