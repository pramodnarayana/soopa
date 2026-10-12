import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from pubsub.aws.error_handlers import DefaultConsumerErrorHandler
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.enums import ConsumerAction
from pubsub.exceptions import ConsumerTerminalError
from pubsub.message import AckableMessage
from pubsub.ports.consumer_error_handler_port import ConsumerErrorHandlerPort
from pubsub.ports.message_consumer_port import MessageConsumerPort
from seedwork.domain.types import JsonDict


class FakeFailingConsumer(MessageConsumerPort):
    async def __aenter__(self) -> "FakeFailingConsumer":
        raise ConsumerTerminalError("QueueDoesNotExist")

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass

    async def poll_raw_message(self) -> AsyncGenerator[AckableMessage | None, None]:
        yield None


class FakeQueueConsumer(MessageConsumerPort):
    def __init__(self, messages: list[AckableMessage]) -> None:
        self.messages = list(messages)

    async def __aenter__(self) -> "FakeQueueConsumer":
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass

    @asynccontextmanager
    async def poll_raw_message(self) -> AsyncGenerator[AckableMessage | None, None]:
        if self.messages:
            yield self.messages.pop(0)
        else:
            yield None


@pytest.mark.asyncio
async def test_sqs_consumer_manager_fails_fast_on_terminal_error() -> None:
    mock_consumer = FakeFailingConsumer()
    fatal_error_called = asyncio.Event()

    def on_fatal_error(exc: BaseException) -> None:
        assert isinstance(exc, ConsumerTerminalError)
        fatal_error_called.set()

    async def mock_handler(payload: JsonDict) -> None:
        pass

    manager = SqsConsumerManager(
        consumer=mock_consumer, handler=mock_handler, on_fatal_error=on_fatal_error
    )
    manager.start()

    try:
        await asyncio.wait_for(fatal_error_called.wait(), timeout=1.0)
    except TimeoutError:
        pytest.fail("on_fatal_error callback was not called within the timeout")

    assert fatal_error_called.is_set()


@pytest.mark.asyncio
async def test_sqs_consumer_manager_processes_message_with_ack() -> None:
    ack_called = False
    nack_called = False

    async def ack() -> None:
        nonlocal ack_called
        ack_called = True

    async def nack() -> None:
        nonlocal nack_called
        nack_called = True

    msg = AckableMessage(payload={"trace_id": "tr_1"}, ack=ack, nack=nack)
    consumer = FakeQueueConsumer([msg])
    processed = asyncio.Event()

    async def handler(payload: JsonDict) -> ConsumerAction:
        processed.set()
        return ConsumerAction.ACK

    manager = SqsConsumerManager(
        consumer=consumer, handler=handler, poll_sleep_seconds=0.01, queue_name="test-queue"
    )
    manager.start()

    await asyncio.wait_for(processed.wait(), timeout=1.0)
    await asyncio.sleep(0.05)
    await manager.stop()

    assert ack_called is True
    assert nack_called is False
    assert manager.is_running is False


@pytest.mark.asyncio
async def test_sqs_consumer_manager_processes_message_with_nack() -> None:
    ack_called = False
    nack_called = False

    async def ack() -> None:
        nonlocal ack_called
        ack_called = True

    async def nack() -> None:
        nonlocal nack_called
        nack_called = True

    msg = AckableMessage(payload={"trace_id": "tr_2"}, ack=ack, nack=nack)
    consumer = FakeQueueConsumer([msg])
    processed = asyncio.Event()

    async def handler(payload: JsonDict) -> ConsumerAction:
        processed.set()
        return ConsumerAction.NACK

    manager = SqsConsumerManager(
        consumer=consumer, handler=handler, poll_sleep_seconds=0.01, queue_name="test-queue"
    )
    manager.start()

    await asyncio.wait_for(processed.wait(), timeout=1.0)
    await asyncio.sleep(0.05)
    await manager.stop()

    assert ack_called is False
    assert nack_called is True


@pytest.mark.asyncio
async def test_sqs_consumer_manager_delegates_to_error_handler_on_exception() -> None:
    class SpyErrorHandler(ConsumerErrorHandlerPort):
        def __init__(self) -> None:
            self.handled_errors: list[Exception] = []
            self.handled_event = asyncio.Event()

        async def handle_error(
            self, error: Exception, ackable_msg: AckableMessage | None, queue_name: str
        ) -> None:
            self.handled_errors.append(error)
            self.handled_event.set()

    error_handler = SpyErrorHandler()

    async def ack() -> None:
        pass

    async def nack() -> None:
        pass

    msg = AckableMessage(payload={"trace_id": "tr_3"}, ack=ack, nack=nack)
    consumer = FakeQueueConsumer([msg])

    async def failing_handler(payload: JsonDict) -> None:
        raise ValueError("Handler failure")

    manager = SqsConsumerManager(
        consumer=consumer,
        handler=failing_handler,
        error_handler=error_handler,
        poll_sleep_seconds=0.01,
        queue_name="test-queue",
    )
    manager.start()

    await asyncio.wait_for(error_handler.handled_event.wait(), timeout=1.0)
    await manager.stop()

    assert len(error_handler.handled_errors) == 1
    assert str(error_handler.handled_errors[0]) == "Handler failure"


@pytest.mark.asyncio
async def test_default_consumer_error_handler_nacks_and_sleeps() -> None:
    nack_called = False

    async def ack() -> None:
        pass

    async def nack() -> None:
        nonlocal nack_called
        nack_called = True

    msg = AckableMessage(payload={"trace_id": "tr_4"}, ack=ack, nack=nack)
    handler = DefaultConsumerErrorHandler(error_sleep_seconds=0.01)

    await handler.handle_error(RuntimeError("Unexpected error"), msg, "test-queue")

    assert nack_called is True


def test_sqs_consumer_manager_background_tasks_and_properties() -> None:
    consumer = FakeQueueConsumer([])

    async def dummy(payload: JsonDict) -> None:
        pass

    manager = SqsConsumerManager(consumer=consumer, handler=dummy)
    assert manager.background_tasks() == []
    assert manager.task is None
