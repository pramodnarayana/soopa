import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest
from identity_worker.adapters.inbound.workers.identity_event_dispatcher import (
    IdentityEventDispatcher,
)

pytestmark = pytest.mark.asyncio


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


async def test_production_listener_propagates_handler_failure():
    # Deprecated by SqsConsumerManager extraction, handled by test_sqs_consumer_handler_failure_prevents_ack
    pass


async def test_malformed_message_is_not_deleted():
    consumer = IdentityEventDispatcher()

    # Missing required fields
    payload = {
        "id": str(uuid.uuid4()),
        # missing source and event_type
    }

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await consumer.dispatch_raw(payload)
