"""
Unit tests for SqsConsumerManager.

All tests mock against MessageConsumerPort — the abstract port —
not against the concrete AwsSqsConsumer class. This is correct
hexagonal testing: we verify the manager's orchestration logic
against the abstraction it depends on.
"""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import botocore.exceptions
import pytest
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.message import AckableMessage
from pubsub.ports.message_consumer_port import MessageConsumerPort

QUEUE_NAME = "test-mgr-queue"


def _make_ackable(payload: dict[str, Any]) -> AckableMessage:
    return AckableMessage(
        payload=payload,
        ack=AsyncMock(),
        nack=AsyncMock(),
    )


def _make_consumer_port(
    messages: list[AckableMessage | None],
) -> MessageConsumerPort:
    """
    Returns a MessageConsumerPort-compliant mock whose poll_raw_message
    yields from the provided list in order.
    """
    consumer = MagicMock(spec=MessageConsumerPort)
    consumer.__aenter__ = AsyncMock(return_value=consumer)
    consumer.__aexit__ = AsyncMock(return_value=False)

    call_index = 0

    @asynccontextmanager
    async def poll_raw_message():
        nonlocal call_index
        msg = messages[call_index] if call_index < len(messages) else None
        call_index += 1
        yield msg

    consumer.poll_raw_message = poll_raw_message
    return consumer


def _make_manager(
    consumer: MessageConsumerPort, handler: Any = None, **kwargs: Any
) -> SqsConsumerManager:
    return SqsConsumerManager(
        consumer=consumer,
        handler=handler or AsyncMock(),
        queue_name=QUEUE_NAME,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Lifecycle: start / stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_creates_background_task_and_sets_is_running():
    consumer = _make_consumer_port([])
    manager = _make_manager(consumer)

    with patch.object(manager, "_run_loop", new_callable=AsyncMock):
        manager.start()
        assert manager.is_running is True
        assert manager.task is not None
        await manager.stop()


@pytest.mark.asyncio
async def test_start_is_idempotent_when_already_running():
    consumer = _make_consumer_port([])
    manager = _make_manager(consumer)

    with patch.object(manager, "_run_loop", new_callable=AsyncMock):
        manager.start()
        first_task = manager.task

        manager.start()  # second call — no-op
        assert manager.task is first_task

        await manager.stop()


@pytest.mark.asyncio
async def test_stop_cancels_task_and_clears_is_running():
    consumer = _make_consumer_port([])
    manager = _make_manager(consumer)

    with patch.object(manager, "_run_loop", new_callable=AsyncMock):
        manager.start()
        await manager.stop()

    assert manager.is_running is False
    assert manager.task is None


@pytest.mark.asyncio
async def test_stop_is_safe_when_not_started():
    consumer = _make_consumer_port([])
    manager = _make_manager(consumer)
    await manager.stop()  # must not raise


# ---------------------------------------------------------------------------
# _poll_continuous — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_continuous_calls_handler_and_acks_on_success():
    handler = AsyncMock()
    payload = {"event_type": "order.created"}
    msg = _make_ackable(payload)

    # First poll yields a message; second stops the loop
    call_count = 0
    manager_ref: list[SqsConsumerManager] = []

    @asynccontextmanager
    async def poll_raw_message():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield msg
        else:
            manager_ref[0].is_running = False
            yield None

    consumer = MagicMock(spec=MessageConsumerPort)
    consumer.__aenter__ = AsyncMock(return_value=consumer)
    consumer.__aexit__ = AsyncMock(return_value=False)
    consumer.poll_raw_message = poll_raw_message

    manager = _make_manager(consumer, handler=handler)
    manager_ref.append(manager)
    manager.is_running = True

    await manager._poll_continuous()

    handler.assert_awaited_once_with(payload)
    msg.ack.assert_awaited_once()


@pytest.mark.asyncio
async def test_poll_continuous_sleeps_when_no_message_available():
    handler = AsyncMock()
    call_count = 0
    manager_ref: list[SqsConsumerManager] = []

    @asynccontextmanager
    async def poll_raw_message():
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            manager_ref[0].is_running = False
        yield None

    consumer = MagicMock(spec=MessageConsumerPort)
    consumer.__aenter__ = AsyncMock(return_value=consumer)
    consumer.__aexit__ = AsyncMock(return_value=False)
    consumer.poll_raw_message = poll_raw_message

    manager = _make_manager(consumer, handler=handler, poll_sleep_seconds=0.05)
    manager_ref.append(manager)
    manager.is_running = True

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await manager._poll_continuous()

    mock_sleep.assert_awaited()
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_continuous_skips_ack_when_handler_raises():
    """Handler exception must NOT ack — SQS will redeliver after visibility timeout."""
    handler = AsyncMock(side_effect=RuntimeError("handler failure"))
    payload = {"event_type": "test.event"}
    msg = _make_ackable(payload)
    call_count = 0
    manager_ref: list[SqsConsumerManager] = []

    @asynccontextmanager
    async def poll_raw_message():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield msg
        else:
            manager_ref[0].is_running = False
            yield None

    consumer = MagicMock(spec=MessageConsumerPort)
    consumer.__aenter__ = AsyncMock(return_value=consumer)
    consumer.__aexit__ = AsyncMock(return_value=False)
    consumer.poll_raw_message = poll_raw_message

    manager = _make_manager(consumer, handler=handler)
    manager_ref.append(manager)
    manager.is_running = True

    await manager._poll_continuous()  # must not raise

    handler.assert_awaited_once_with(payload)
    msg.ack.assert_not_awaited()


# ---------------------------------------------------------------------------
# _poll_continuous — ClientError handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_continuous_sleeps_on_transient_client_error():
    handler = AsyncMock()
    call_count = 0
    manager_ref: list[SqsConsumerManager] = []

    @asynccontextmanager
    async def poll_raw_message():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "RequestThrottled", "Message": "Throttled"}},
                "ReceiveMessage",
            )
        manager_ref[0].is_running = False
        yield None

    consumer = MagicMock(spec=MessageConsumerPort)
    consumer.__aenter__ = AsyncMock(return_value=consumer)
    consumer.__aexit__ = AsyncMock(return_value=False)
    consumer.poll_raw_message = poll_raw_message

    manager = _make_manager(consumer, handler=handler, error_sleep_seconds=0.01)
    manager_ref.append(manager)
    manager.is_running = True

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await manager._poll_continuous()

    mock_sleep.assert_awaited()


@pytest.mark.asyncio
async def test_poll_continuous_reraises_on_terminal_client_error():
    @asynccontextmanager
    async def poll_raw_message():
        raise botocore.exceptions.ClientError(
            {"Error": {"Code": "AWS.SimpleQueueService.NonExistentQueue", "Message": "No queue"}},
            "ReceiveMessage",
        )
        yield None  # unreachable

    consumer = MagicMock(spec=MessageConsumerPort)
    consumer.__aenter__ = AsyncMock(return_value=consumer)
    consumer.__aexit__ = AsyncMock(return_value=False)
    consumer.poll_raw_message = poll_raw_message

    manager = _make_manager(consumer)
    manager.is_running = True

    with pytest.raises(botocore.exceptions.ClientError):
        await manager._poll_continuous()


# ---------------------------------------------------------------------------
# _run_loop — reconnection on transient error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_loop_reconnects_after_transient_boto_core_error():
    """
    When _poll_continuous raises BotoCoreError the loop must sleep and then
    re-enter the consumer context manager and retry.
    """
    call_count = 0

    async def patched_poll_continuous():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise botocore.exceptions.BotoCoreError()
        # Second invocation stops the loop cleanly
        manager.is_running = False

    consumer = MagicMock(spec=MessageConsumerPort)
    consumer.__aenter__ = AsyncMock(return_value=consumer)
    consumer.__aexit__ = AsyncMock(return_value=False)

    manager = _make_manager(consumer, error_sleep_seconds=0.0)
    manager._poll_continuous = patched_poll_continuous  # type: ignore[method-assign]
    manager.is_running = True

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await manager._run_loop()

    assert call_count == 2  # retried once after transient error


@pytest.mark.asyncio
async def test_run_loop_raises_on_unhandled_exception():
    """
    A non-BotoCoreError exception in _poll_continuous must bubble up and
    terminate the loop — it is treated as a fatal error.
    """
    consumer = MagicMock(spec=MessageConsumerPort)
    consumer.__aenter__ = AsyncMock(return_value=consumer)
    consumer.__aexit__ = AsyncMock(return_value=False)

    manager = _make_manager(consumer)
    manager.is_running = True

    async def raising_poll_continuous() -> None:
        raise RuntimeError("unexpected bug")

    manager._poll_continuous = raising_poll_continuous  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="unexpected bug"):
        await manager._run_loop()
