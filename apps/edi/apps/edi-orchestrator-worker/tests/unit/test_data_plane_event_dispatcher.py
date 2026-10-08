import pytest
from pubsub.exceptions import ConsumerTerminalError

from worker.adapters.inbound.workers.edi_data_plane_event_dispatcher import (
    EdiDataPlaneEventDispatcher,
    EdiDataPlaneEventMessage,
)

pytestmark = pytest.mark.asyncio


def _make_body(**overrides: object) -> dict:
    """
    Builds a standard serialized EventEnvelope dict as emitted by AwsSqsConsumer.
    The transport layer always yields raw JsonDict — translation happens in the dispatcher.
    """
    body = {
        "id": "msg-1",
        "source": "soopa.edi",
        "tenant_id": "tenant123",
        "event_type": "TRANSFORMATION_REQUESTED",
        "idempotency_key": "idem123",
        "payload": {"trace_id": "trace123", "direction": "INBOUND"},
    }
    body.update(overrides)
    return body


async def test_sqs_consumer_success() -> None:
    """Valid raw envelope dict is translated and delegated to the callback."""
    events_received: list[EdiDataPlaneEventMessage] = []

    async def real_callback(event: EdiDataPlaneEventMessage) -> None:
        events_received.append(event)

    consumer = EdiDataPlaneEventDispatcher(callback=real_callback)
    await consumer.handle(_make_body())

    assert len(events_received) == 1
    event = events_received[0]
    assert event.tenant_id == "tenant123"
    assert event.trace_id == "trace123"
    assert event.event_type == "TRANSFORMATION_REQUESTED"
    assert event.idempotency_key == "idem123"
    assert event.payload == {"trace_id": "trace123", "direction": "INBOUND"}


async def test_sqs_consumer_missing_trace_id_raises_terminal_error() -> None:
    """Messages with a payload missing trace_id fail validation and raise ConsumerTerminalError."""
    events_received: list[EdiDataPlaneEventMessage] = []

    async def real_callback(event: EdiDataPlaneEventMessage) -> None:
        events_received.append(event)

    consumer = EdiDataPlaneEventDispatcher(callback=real_callback)
    with pytest.raises(ConsumerTerminalError, match="Permanently malformed EDI data plane message"):
        await consumer.handle(_make_body(payload={}))

    assert len(events_received) == 0


async def test_sqs_consumer_missing_tenant_id_raises_terminal_error() -> None:
    """Messages with an empty tenant_id fail validation and raise ConsumerTerminalError."""
    events_received: list[EdiDataPlaneEventMessage] = []

    async def real_callback(event: EdiDataPlaneEventMessage) -> None:
        events_received.append(event)

    consumer = EdiDataPlaneEventDispatcher(callback=real_callback)
    with pytest.raises(ConsumerTerminalError, match="Permanently malformed EDI data plane message"):
        await consumer.handle(_make_body(tenant_id=""))

    assert len(events_received) == 0


async def test_sqs_consumer_missing_idempotency_key_raises_terminal_error() -> None:
    """Messages with an empty idempotency_key fail validation and raise ConsumerTerminalError."""
    events_received: list[EdiDataPlaneEventMessage] = []

    async def real_callback(event: EdiDataPlaneEventMessage) -> None:
        events_received.append(event)

    consumer = EdiDataPlaneEventDispatcher(callback=real_callback)
    with pytest.raises(ConsumerTerminalError, match="Permanently malformed EDI data plane message"):
        await consumer.handle(_make_body(idempotency_key=""))

    assert len(events_received) == 0


async def test_sqs_consumer_callback_exception_propogates() -> None:
    """Exceptions raised by the domain callback must propagate to the SQS manager to prevent ack."""

    async def exploding_callback(event: EdiDataPlaneEventMessage) -> None:
        raise RuntimeError("Business Logic Error")

    consumer = EdiDataPlaneEventDispatcher(callback=exploding_callback)

    with pytest.raises(RuntimeError, match="Business Logic Error"):
        await consumer.handle(_make_body())
