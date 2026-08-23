from unittest.mock import AsyncMock

import pytest

from worker.adapters.inbound.workers.edi_data_plane_events_sqs_consumer import (
    EdiDataPlaneEventMessage,
    EdiDataPlaneEventsSqsConsumer,
)

pytestmark = pytest.mark.asyncio


async def test_sqs_consumer_success() -> None:
    """Test that a valid SQS JSON body is parsed and delegated to the callback."""
    mock_callback = AsyncMock()
    consumer = EdiDataPlaneEventsSqsConsumer(callback=mock_callback)

    body = {
        "tenant_id": "tenant123",
        "event_type": "TRANSFORM_EVENT",
        "idempotency_key": "idem123",
        "payload": {"trace_id": "trace123", "direction": "INBOUND"},
    }

    await consumer.handle(body)

    # Verify callback was called exactly once with the correctly parsed DTO
    mock_callback.assert_called_once()
    event: EdiDataPlaneEventMessage = mock_callback.call_args[0][0]

    assert event.tenant_id == "tenant123"
    assert event.trace_id == "trace123"
    assert event.event_type == "TRANSFORM_EVENT"
    assert event.idempotency_key == "idem123"
    assert event.payload == {"trace_id": "trace123", "direction": "INBOUND"}


async def test_sqs_consumer_missing_trace_id_drops_message() -> None:
    """Test that messages missing trace_id are dropped (callback not invoked)."""
    mock_callback = AsyncMock()
    consumer = EdiDataPlaneEventsSqsConsumer(callback=mock_callback)

    body = {
        "tenant_id": "tenant123",
        "event_type": "TRANSFORM_EVENT",
        "payload": {
            # Missing trace_id
        },
    }

    await consumer.handle(body)

    mock_callback.assert_not_called()


async def test_sqs_consumer_missing_tenant_id_drops_message() -> None:
    """Test that messages missing tenant_id are dropped (callback not invoked)."""
    mock_callback = AsyncMock()
    consumer = EdiDataPlaneEventsSqsConsumer(callback=mock_callback)

    body = {"event_type": "TRANSFORM_EVENT", "payload": {"trace_id": "trace123"}}

    await consumer.handle(body)

    mock_callback.assert_not_called()


async def test_sqs_consumer_callback_exception_propogates() -> None:
    """Test that if the callback throws an exception, it propagates up."""
    mock_callback = AsyncMock(side_effect=RuntimeError("Business Logic Error"))
    consumer = EdiDataPlaneEventsSqsConsumer(callback=mock_callback)

    body = {
        "tenant_id": "tenant123",
        "event_type": "TRANSFORM_EVENT",
        "payload": {"trace_id": "trace123"},
    }

    with pytest.raises(RuntimeError, match="Business Logic Error"):
        await consumer.handle(body)
