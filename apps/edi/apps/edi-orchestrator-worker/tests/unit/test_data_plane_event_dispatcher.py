import pytest

from worker.adapters.inbound.workers.edi_data_plane_event_dispatcher import (
    EdiDataPlaneEventDispatcher,
    EdiDataPlaneEventMessage,
)

pytestmark = pytest.mark.asyncio


async def test_sqs_consumer_success() -> None:
    """Test that a valid SQS JSON body is parsed and delegated to the callback."""
    events_received = []

    async def real_callback(event: EdiDataPlaneEventMessage) -> None:
        events_received.append(event)

    consumer = EdiDataPlaneEventDispatcher(callback=real_callback)

    body = {
        "tenant_id": "tenant123",
        "event_type": "TRANSFORM_EVENT",
        "idempotency_key": "idem123",
        "payload": {"trace_id": "trace123", "direction": "INBOUND"},
    }

    await consumer.handle(body)

    # Verify callback was called exactly once with the correctly parsed DTO
    assert len(events_received) == 1
    event = events_received[0]

    assert event.tenant_id == "tenant123"
    assert event.trace_id == "trace123"
    assert event.event_type == "TRANSFORM_EVENT"
    assert event.idempotency_key == "idem123"
    assert event.payload == {"trace_id": "trace123", "direction": "INBOUND"}


async def test_sqs_consumer_missing_trace_id_drops_message() -> None:
    """Test that messages missing trace_id are dropped (callback not invoked)."""
    events_received = []

    async def real_callback(event: EdiDataPlaneEventMessage) -> None:
        events_received.append(event)

    consumer = EdiDataPlaneEventDispatcher(callback=real_callback)

    body = {
        "tenant_id": "tenant123",
        "event_type": "TRANSFORM_EVENT",
        "payload": {
            # Missing trace_id
        },
    }

    await consumer.handle(body)

    assert len(events_received) == 0


async def test_sqs_consumer_missing_tenant_id_drops_message() -> None:
    """Test that messages missing tenant_id are dropped (callback not invoked)."""
    events_received = []

    async def real_callback(event: EdiDataPlaneEventMessage) -> None:
        events_received.append(event)

    consumer = EdiDataPlaneEventDispatcher(callback=real_callback)

    body = {"event_type": "TRANSFORM_EVENT", "payload": {"trace_id": "trace123"}}

    await consumer.handle(body)

    assert len(events_received) == 0


async def test_sqs_consumer_callback_exception_propogates() -> None:
    """Test that if the callback throws an exception, it propagates up."""

    async def exploding_callback(event: EdiDataPlaneEventMessage) -> None:
        raise RuntimeError("Business Logic Error")

    consumer = EdiDataPlaneEventDispatcher(callback=exploding_callback)

    body = {
        "tenant_id": "tenant123",
        "event_type": "TRANSFORM_EVENT",
        "payload": {"trace_id": "trace123"},
    }

    with pytest.raises(RuntimeError, match="Business Logic Error"):
        await consumer.handle(body)
