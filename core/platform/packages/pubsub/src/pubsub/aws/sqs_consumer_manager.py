import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from pubsub.aws.error_handlers import DefaultConsumerErrorHandler
from pubsub.enums import ConsumerAction
from pubsub.exceptions import ConsumerTerminalError, ConsumerTransientError
from pubsub.message import AckableMessage
from pubsub.ports.consumer_error_handler_port import ConsumerErrorHandlerPort
from pubsub.ports.message_consumer_port import MessageConsumerPort
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


async def _execute_ack(msg: AckableMessage) -> None:
    await msg.ack()


async def _execute_nack(msg: AckableMessage) -> None:
    await msg.nack()


CONSUMER_ACTION_STRATEGIES: dict[ConsumerAction, Callable[[AckableMessage], Awaitable[None]]] = {
    ConsumerAction.ACK: _execute_ack,
    ConsumerAction.NACK: _execute_nack,
    ConsumerAction.DLQ: _execute_nack,  # SQS redrive handles DLQ routing automatically on nack
}


class SqsConsumerManager:
    """
    Centralized Message Pump for polling a message broker and dispatching to a
    pure Python callback handler.

    Accepts any MessageConsumerPort implementation — AwsSqsConsumer in production,
    InMemoryEventBus in tests. This satisfies the Dependency Inversion Principle:
    the manager depends on the abstraction, not the concrete AWS driver.

    Callers (worker entrypoints / DI containers) are responsible for constructing
    and injecting the consumer, which keeps object construction at the composition root.
    """

    def __init__(
        self,
        consumer: MessageConsumerPort,
        handler: Callable[[JsonDict], Awaitable[ConsumerAction | None]],
        queue_name: str = "",
        poll_sleep_seconds: float = 0.1,
        error_sleep_seconds: float = 5.0,
        error_handler: ConsumerErrorHandlerPort | None = None,
        on_fatal_error: Callable[[BaseException], None] | None = None,
    ):
        self.consumer = consumer
        self.handler = handler
        # queue_name is kept for logging context only — the consumer owns the queue detail
        self.queue_name = queue_name
        self.poll_sleep_seconds = poll_sleep_seconds
        self.error_sleep_seconds = error_sleep_seconds
        self.on_fatal_error = on_fatal_error

        # Use injected strategy or fallback to default resilient strategy
        self.error_handler = error_handler or DefaultConsumerErrorHandler(error_sleep_seconds)

        self.is_running = False
        self._task: asyncio.Task[None] | None = None

    def background_tasks(self) -> list[asyncio.Task[Any]]:
        return [self._task] if self._task else []

    @property
    def task(self) -> asyncio.Task[None] | None:
        """Returns the internal asyncio task for the consumer loop."""
        return self._task

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            exc = task.exception()
            if exc:
                logger.error(
                    "sqs_consumer_manager_background_task_crashed",
                    queue=self.queue_name,
                    exc_info=exc,
                )
                if self.on_fatal_error:
                    self.on_fatal_error(exc)
                else:
                    loop = asyncio.get_event_loop()
                    loop.call_soon_threadsafe(loop.stop)

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop())
            self._task.add_done_callback(self._on_task_done)
            logger.info("sqs_consumer_manager_started", queue=self.queue_name)

    async def stop(self) -> None:
        self.is_running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("sqs_consumer_manager_stopped", queue=self.queue_name)

    async def _run_loop(self) -> None:
        while self.is_running:
            try:
                async with self.consumer:
                    await self._poll_continuous()
            except asyncio.CancelledError:
                self.is_running = False
                raise
            except ConsumerTerminalError:
                logger.error("sqs_consumer_manager_terminal_error", queue=self.queue_name)
                raise
            except ConsumerTransientError as e:
                logger.warning(
                    "sqs_consumer_manager_transient_error", queue=self.queue_name, reason=str(e)
                )
                await asyncio.sleep(self.error_sleep_seconds)
            except Exception:
                logger.exception(
                    "sqs_consumer_manager_unhandled_fatal_error", queue=self.queue_name
                )
                raise

    async def _poll_continuous(self) -> None:
        while self.is_running:
            ackable_msg = None
            try:
                async with self.consumer.poll_raw_message() as ackable_msg:
                    if not ackable_msg:
                        await asyncio.sleep(self.poll_sleep_seconds)
                        continue

                    # Dispatch to the pure callback handler.
                    # A raised exception here means we skip the ack(),
                    # and it will be visible again in SQS after visibility timeout.
                    keys = []
                    if isinstance(ackable_msg.payload, dict):
                        keys = list(ackable_msg.payload.keys())

                    logger.info(
                        "sqs_consumer_manager_received_message",
                        queue=self.queue_name,
                        payload_keys=keys,
                    )

                    action = await self.handler(ackable_msg.payload)
                    action = action or ConsumerAction.ACK

                    strategy_fn = CONSUMER_ACTION_STRATEGIES.get(action, _execute_ack)
                    await strategy_fn(ackable_msg)

            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001 - Message pump loop must catch all message processing errors to delegate to error_handler and prevent worker crash
                await self.error_handler.handle_error(e, ackable_msg, self.queue_name)
