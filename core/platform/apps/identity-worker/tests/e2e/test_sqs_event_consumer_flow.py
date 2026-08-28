import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from identity_worker.adapters.inbound.workers.identity_event_dispatcher import (
    IdentityEventDispatcher,
)
from identity_worker.ports.inbound.identity_event_consumer_port import (
    IdentityEventConsumerPort,
    IdentityEventMessage,
)
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer

pytestmark = pytest.mark.asyncio


class FakeIdentityEventConsumer(IdentityEventConsumerPort):
    def __init__(self, events: list[IdentityEventMessage]):
        self.events = events
        self.processed = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    @asynccontextmanager
    async def process_next_event(self):
        if not self.events:
            yield None
            return

        event = self.events.pop(0)
        try:
            yield event
            self.processed.append(event)
        except Exception:
            # Simulated NACK
            self.events.append(event)
            raise


async def test_sqs_consumer_dispatch_flow():
    # 1. Setup Fake Listener with a single event
    test_event = IdentityEventMessage(
        id=str(uuid.uuid4()),
        source="test",
        event_type="TenantProvisioned",
        payload={"tenant_id": "tenant-123"},
    )
    listener = FakeIdentityEventConsumer([test_event])

    # 2. Setup Consumer
    consumer = IdentityEventDispatcher(listener)

    # 3. Setup Fake Handler (representing IdentitySyncService)
    handled = asyncio.Event()

    async def handler(event):
        handled.set()

    mock_handler = AsyncMock(side_effect=handler)
    consumer.subscribe("TenantProvisioned", mock_handler)

    # 4. Run consumer until the handler confirms dispatch
    consumer.start()
    await asyncio.wait_for(handled.wait(), timeout=1)
    await consumer.stop()

    # 5. Verify flow
    mock_handler.assert_called_once()
    called_event = mock_handler.call_args[0][0]
    assert called_event.event_type == "TenantProvisioned"
    assert called_event.payload["tenant_id"] == "tenant-123"

    # Verify event was acknowledged (removed from queue)
    assert len(listener.events) == 0
    assert len(listener.processed) == 1


async def test_sqs_consumer_handler_failure_prevents_ack():
    test_event = IdentityEventMessage(
        id=str(uuid.uuid4()),
        source="test",
        event_type="TenantProvisioned",
        payload={"tenant_id": "tenant-123"},
    )
    listener = FakeIdentityEventConsumer([test_event])
    consumer = IdentityEventDispatcher(listener)
    handled = asyncio.Event()

    # Setup handler that raises an exception
    async def failing_handler(event):
        handled.set()
        raise RuntimeError("Handler Failed")

    consumer.subscribe("TenantProvisioned", failing_handler)

    consumer.start()
    await asyncio.wait_for(handled.wait(), timeout=1)
    await consumer.stop()

    # Event should be re-queued (NACKed)
    assert len(listener.events) == 1
    assert len(listener.processed) == 0


async def test_production_listener_propagates_handler_failure():
    event_data = {
        "id": str(uuid.uuid4()),
        "source": "test",
        "event_type": "TenantProvisioned",
        "payload": {"tenant_id": "tenant-123"},
    }
    sqs_client = AsyncMock()
    sqs_client.receive_message.return_value = {
        "Messages": [
            {
                "ReceiptHandle": "receipt-1",
                "MessageId": "message-1",
                "Body": json.dumps(event_data),
            }
        ]
    }
    listener = AwsSqsConsumer(queue_name="identity-events")
    consumer = IdentityEventDispatcher(listener)

    async def failing_handler(event):
        raise RuntimeError("Handler Failed")

    consumer.subscribe("TenantProvisioned", failing_handler)

    with pytest.raises(RuntimeError, match="Handler Failed"):
        async with listener._process_with_client(sqs_client) as event:
            assert event is not None
            await consumer._dispatch(event)

    sqs_client.delete_message.assert_not_awaited()


async def test_malformed_message_is_not_deleted():
    sqs_client = AsyncMock()
    sqs_client.receive_message.return_value = {
        "Messages": [
            {
                "ReceiptHandle": "receipt-1",
                "MessageId": "message-1",
                "Body": "not-json",
            }
        ]
    }
    listener = AwsSqsConsumer(queue_name="identity-events")

    async with listener._process_with_client(sqs_client) as event:
        assert event is None

    sqs_client.delete_message.assert_not_awaited()
