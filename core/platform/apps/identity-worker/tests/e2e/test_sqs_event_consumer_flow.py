"""
E2E-style tests for the SQS event consumer flow in identity-worker.

These tests verify the full dispatch chain: raw SQS payload → IdentityEventDispatcher
→ registered handler. The SqsConsumerManager is tested with an injected
MessageConsumerPort mock (the correct hexagonal approach), not via internal
sqs_consumer._client manipulation.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from identity_worker.adapters.inbound.workers.identity_event_dispatcher import (
    IdentityEventDispatcher,
)
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.message import AckableMessage
from pubsub.ports.message_consumer_port import MessageConsumerPort

pytestmark = pytest.mark.asyncio


def _make_single_message_manager(
    dispatcher: IdentityEventDispatcher,
    payload: dict[str, Any],
) -> SqsConsumerManager:
    """
    Build a SqsConsumerManager backed by a one-shot MessageConsumerPort mock.

    After the first message is dispatched the manager stops itself, preventing
    an infinite poll loop in tests.
    """
    manager_ref: list[SqsConsumerManager] = []

    call_count = 0

    @asynccontextmanager
    async def poll_raw_message():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield AckableMessage(
                payload=payload,
                ack=AsyncMock(),
                nack=AsyncMock(),
            )
        else:
            # Stop the loop after the first message
            if manager_ref:
                manager_ref[0].is_running = False
            yield None

    consumer = MagicMock(spec=MessageConsumerPort)
    consumer.__aenter__ = AsyncMock(return_value=consumer)
    consumer.__aexit__ = AsyncMock(return_value=False)
    consumer.poll_raw_message = poll_raw_message

    async def handler(raw_message: dict[str, Any]) -> None:
        # Stop after first dispatch so the test doesn't loop forever
        if manager_ref:
            manager_ref[0].is_running = False
        await dispatcher.dispatch_raw(raw_message)

    manager = SqsConsumerManager(
        consumer=consumer,
        queue_name="identity-events",
        handler=handler,
    )
    manager_ref.append(manager)
    return manager


# ---------------------------------------------------------------------------
# Dispatcher unit tests (no SqsConsumerManager involvement)
# ---------------------------------------------------------------------------


async def test_identity_event_dispatcher_routes_to_correct_handler():
    consumer = IdentityEventDispatcher()
    handled = asyncio.Event()

    async def handler(event: Any) -> None:
        handled.set()

    mock_handler = AsyncMock(side_effect=handler)
    consumer.subscribe("TenantProvisioned", mock_handler)

    payload = {
        "id": str(uuid.uuid4()),
        "source": "test",
        "event_type": "TenantProvisioned",
        "payload": {"tenant_id": "tenant-123"},
    }
    await consumer.dispatch_raw(payload)

    mock_handler.assert_called_once()
    called_event = mock_handler.call_args[0][0]
    assert called_event.event_type == "TenantProvisioned"
    assert called_event.payload["tenant_id"] == "tenant-123"


async def test_handler_failure_propagates_to_prevent_ack():
    """Exception in a handler must bubble up so SqsConsumerManager skips the ack."""
    consumer = IdentityEventDispatcher()

    async def failing_handler(event: Any) -> None:
        raise RuntimeError("Handler Failed")

    mock_handler = AsyncMock(side_effect=failing_handler)
    consumer.subscribe("TenantProvisioned", mock_handler)

    payload = {
        "id": str(uuid.uuid4()),
        "source": "test",
        "event_type": "TenantProvisioned",
        "payload": {"tenant_id": "tenant-123"},
    }

    with pytest.raises(RuntimeError, match="Handler Failed"):
        await consumer.dispatch_raw(payload)

    mock_handler.assert_called_once()


# ---------------------------------------------------------------------------
# Full pipeline tests (SqsConsumerManager → dispatcher → handler)
# ---------------------------------------------------------------------------


async def test_manager_dispatches_message_to_subscribed_handler():
    consumer = IdentityEventDispatcher()
    handled = asyncio.Event()

    async def handler(event: Any) -> None:
        handled.set()

    mock_handler = AsyncMock(side_effect=handler)
    consumer.subscribe("TenantProvisioned", mock_handler)

    payload = {
        "id": str(uuid.uuid4()),
        "source": "test",
        "event_type": "TenantProvisioned",
        "payload": {"tenant_id": "tenant-123"},
    }
    manager = _make_single_message_manager(consumer, payload)
    manager.is_running = True

    await manager._poll_continuous()

    mock_handler.assert_called_once()


async def test_manager_does_not_ack_when_handler_raises():
    """
    When the domain handler raises, the SqsConsumerManager must NOT ack the message.
    The message will become visible again in SQS after its visibility timeout.
    """
    consumer = IdentityEventDispatcher()
    failing_handler = AsyncMock(side_effect=RuntimeError("Handler Failed"))
    consumer.subscribe("TenantProvisioned", failing_handler)

    payload = {
        "id": str(uuid.uuid4()),
        "source": "test",
        "event_type": "TenantProvisioned",
        "payload": {"tenant_id": "tenant-123"},
    }

    ack_mock = AsyncMock()
    call_count = 0

    @asynccontextmanager
    async def poll_raw_message():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield AckableMessage(payload=payload, ack=ack_mock, nack=AsyncMock())
        else:
            manager.is_running = False
            yield None

    port = MagicMock(spec=MessageConsumerPort)
    port.__aenter__ = AsyncMock(return_value=port)
    port.__aexit__ = AsyncMock(return_value=False)
    port.poll_raw_message = poll_raw_message

    manager = SqsConsumerManager(
        consumer=port,
        queue_name="identity-events",
        handler=consumer.dispatch_raw,
    )
    manager.is_running = True

    await manager._poll_continuous()  # must not raise

    failing_handler.assert_awaited_once()
    ack_mock.assert_not_awaited()


async def test_malformed_message_does_not_ack():
    """A payload missing required fields must not be acked."""
    consumer = IdentityEventDispatcher()
    # No handlers registered — dispatch_raw will likely raise or silently drop
    payload = {"id": str(uuid.uuid4())}  # missing event_type, source, payload

    ack_mock = AsyncMock()
    call_count = 0

    @asynccontextmanager
    async def poll_raw_message():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield AckableMessage(payload=payload, ack=ack_mock, nack=AsyncMock())
        else:
            manager.is_running = False
            yield None

    port = MagicMock(spec=MessageConsumerPort)
    port.__aenter__ = AsyncMock(return_value=port)
    port.__aexit__ = AsyncMock(return_value=False)
    port.poll_raw_message = poll_raw_message

    manager = SqsConsumerManager(
        consumer=port,
        queue_name="identity-events",
        handler=consumer.dispatch_raw,
    )
    manager.is_running = True

    await manager._poll_continuous()

    ack_mock.assert_not_awaited()
