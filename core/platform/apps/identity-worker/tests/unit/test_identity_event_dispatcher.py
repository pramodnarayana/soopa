from collections.abc import Generator

import pytest
from identity_worker.adapters.inbound.workers.identity_event_dispatcher import (
    IdentityEventDispatcher,
)
from identity_worker.ports.inbound.identity_event_consumer_port import IdentityEventMessage


class CustomAwaitable:
    def __init__(self) -> None:
        self.awaited = False

    def __await__(self) -> Generator[None, None, None]:
        self.awaited = True
        if False:
            yield
        return None


@pytest.mark.asyncio
async def test_dispatch_awaits_custom_awaitable_handler_result() -> None:
    dispatcher = IdentityEventDispatcher()
    result = CustomAwaitable()

    def handler(_event: IdentityEventMessage) -> CustomAwaitable:
        return result

    dispatcher.subscribe("user.created", handler)
    event = IdentityEventMessage(
        id="evt_1",
        source="identity",
        event_type="user.created",
        payload={},
        idempotency_key=None,
        tenant_id="ten_1",
    )

    await dispatcher._dispatch(event)

    assert result.awaited is True


import asyncio
from typing import Any
from unittest.mock import AsyncMock

from identity.domain.constants import IdentityEventType
from seedwork import generate_id


async def test_identity_event_dispatcher_routes_to_correct_handler():
    consumer = IdentityEventDispatcher()
    handled = asyncio.Event()

    async def handler(event: Any) -> None:
        handled.set()

    mock_handler = AsyncMock(side_effect=handler)
    consumer.subscribe(IdentityEventType.TENANT_PROVISIONED, mock_handler)

    payload = {
        "id": generate_id("id"),
        "source": "test",
        "event_type": IdentityEventType.TENANT_PROVISIONED,
        "payload": {"tenant_id": "tenant-123"},
    }
    await consumer.dispatch_raw(payload)

    mock_handler.assert_called_once()
    called_event = mock_handler.call_args[0][0]
    assert called_event.event_type == IdentityEventType.TENANT_PROVISIONED
    assert called_event.payload["tenant_id"] == "tenant-123"


async def test_handler_failure_propagates_to_prevent_ack():
    consumer = IdentityEventDispatcher()

    async def failing_handler(event: Any) -> None:
        raise RuntimeError("Handler Failed")

    mock_handler = AsyncMock(side_effect=failing_handler)
    consumer.subscribe(IdentityEventType.TENANT_PROVISIONED, mock_handler)

    payload = {
        "id": generate_id("id"),
        "source": "test",
        "event_type": IdentityEventType.TENANT_PROVISIONED,
        "payload": {"tenant_id": "tenant-123"},
    }

    with pytest.raises(RuntimeError, match="Handler Failed"):
        await consumer.dispatch_raw(payload)

    mock_handler.assert_called_once()
