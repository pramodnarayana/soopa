import asyncio
import json
import uuid
from unittest.mock import AsyncMock

import pytest
from identity_worker.adapters.inbound.workers.identity_event_dispatcher import (
    IdentityEventDispatcher,
)
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager

pytestmark = pytest.mark.asyncio


def _manager_with_message(
    consumer: IdentityEventDispatcher, payload: dict[str, object]
) -> tuple[SqsConsumerManager, AsyncMock]:
    manager: SqsConsumerManager

    async def dispatch_once(raw_message: dict[str, object]) -> None:
        manager.is_running = False
        await consumer.dispatch_raw(raw_message)

    manager = SqsConsumerManager(queue_name="identity-events", handler=dispatch_once)
    sqs_client = AsyncMock()
    sqs_client.get_queue_url.return_value = {"QueueUrl": "https://sqs.test/identity-events"}
    sqs_client.receive_message.return_value = {
        "Messages": [
            {
                "ReceiptHandle": "receipt-1",
                "MessageId": "message-1",
                "Body": json.dumps(payload),
            }
        ]
    }
    manager.sqs_consumer._client = sqs_client
    manager.is_running = True
    return manager, sqs_client


async def test_sqs_consumer_dispatch_flow():
    # 2. Setup Consumer
    consumer = IdentityEventDispatcher()

    # 3. Setup Fake Handler (representing IdentitySyncService)
    handled = asyncio.Event()

    async def handler(event):
        handled.set()

    mock_handler = AsyncMock(side_effect=handler)
    consumer.subscribe("TenantProvisioned", mock_handler)

    # 4. Run consumer
    payload = {
        "id": str(uuid.uuid4()),
        "source": "test",
        "event_type": "TenantProvisioned",
        "payload": {"tenant_id": "tenant-123"},
    }
    await consumer.dispatch_raw(payload)

    # 5. Verify flow
    mock_handler.assert_called_once()
    called_event = mock_handler.call_args[0][0]
    assert called_event.event_type == "TenantProvisioned"
    assert called_event.payload["tenant_id"] == "tenant-123"


async def test_sqs_consumer_handler_failure_prevents_ack():
    consumer = IdentityEventDispatcher()
    handled = asyncio.Event()

    # Setup handler that raises an exception
    async def failing_handler(event):
        handled.set()
        raise RuntimeError("Handler Failed")

    mock_handler = AsyncMock(side_effect=failing_handler)
    consumer.subscribe("TenantProvisioned", mock_handler)

    payload = {
        "id": str(uuid.uuid4()),
        "source": "test",
        "event_type": "TenantProvisioned",
        "payload": {"tenant_id": "tenant-123"},
    }

    # Exception should bubble up to prevent ACK
    with pytest.raises(RuntimeError, match="Handler Failed"):
        await consumer.dispatch_raw(payload)

    mock_handler.assert_called_once()


async def test_manager_does_not_delete_message_when_handler_fails():
    consumer = IdentityEventDispatcher()
    failing_handler = AsyncMock(side_effect=RuntimeError("Handler Failed"))
    consumer.subscribe("TenantProvisioned", failing_handler)
    payload = {
        "id": str(uuid.uuid4()),
        "source": "test",
        "event_type": "TenantProvisioned",
        "payload": {"tenant_id": "tenant-123"},
    }
    manager, sqs_client = _manager_with_message(consumer, payload)

    await manager._poll_continuous()

    failing_handler.assert_awaited_once()
    sqs_client.delete_message.assert_not_awaited()


async def test_malformed_message_is_not_deleted():
    consumer = IdentityEventDispatcher()
    payload = {
        "id": str(uuid.uuid4()),
    }
    manager, sqs_client = _manager_with_message(consumer, payload)

    await manager._poll_continuous()

    sqs_client.delete_message.assert_not_awaited()
