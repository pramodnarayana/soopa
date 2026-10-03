import asyncio

import pytest
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.exceptions import ConsumerTerminalError
from pubsub.ports.message_consumer_port import MessageConsumerPort


class FakeFailingConsumer(MessageConsumerPort):
    async def __aenter__(self) -> "FakeFailingConsumer":
        raise ConsumerTerminalError("QueueDoesNotExist")

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    async def poll_raw_message(self):
        yield None


@pytest.mark.asyncio
async def test_sqs_consumer_manager_fails_fast_on_terminal_error():
    """
    Ensures that if the consumer loop crashes with a ConsumerTerminalError,
    the background asyncio task triggers the on_fatal_error callback,
    preventing silent failures in production.
    """
    mock_consumer = FakeFailingConsumer()

    fatal_error_called = asyncio.Event()

    def on_fatal_error(exc: BaseException) -> None:
        assert isinstance(exc, ConsumerTerminalError)
        fatal_error_called.set()

    async def mock_handler(payload):
        pass

    manager = SqsConsumerManager(
        consumer=mock_consumer, handler=mock_handler, on_fatal_error=on_fatal_error
    )

    manager.start()

    # Wait briefly for the task to crash and the callback to execute
    try:
        await asyncio.wait_for(fatal_error_called.wait(), timeout=1.0)
    except TimeoutError:
        pytest.fail("on_fatal_error callback was not called within the timeout")

    assert fatal_error_called.is_set()
