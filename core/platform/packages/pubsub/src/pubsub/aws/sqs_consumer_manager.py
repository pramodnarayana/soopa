import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

import botocore.exceptions
import structlog
from pubsub.ports.message_consumer_port import MessageConsumerPort

logger = structlog.get_logger(__name__)


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
        handler: Callable[[dict[str, Any]], Awaitable[None]],
        queue_name: str = "",
        poll_sleep_seconds: float = 0.1,
        error_sleep_seconds: float = 5.0,
    ):
        self.consumer = consumer
        self.handler = handler
        # queue_name is kept for logging context only — the consumer owns the queue detail
        self.queue_name = queue_name
        self.poll_sleep_seconds = poll_sleep_seconds
        self.error_sleep_seconds = error_sleep_seconds

        self.is_running = False
        self._task: asyncio.Task[None] | None = None

    @property
    def task(self) -> asyncio.Task[None] | None:
        """Returns the internal asyncio task for the consumer loop."""
        return self._task

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._run_loop())
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
            except botocore.exceptions.ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code in (
                    "AWS.SimpleQueueService.NonExistentQueue",
                    "InvalidParameterValue",
                    "AccessDenied",
                ):
                    logger.exception("sqs_consumer_manager_terminal_error", queue=self.queue_name)
                    raise
                logger.exception("sqs_consumer_manager_transient_error", queue=self.queue_name)
                await asyncio.sleep(self.error_sleep_seconds)
            except botocore.exceptions.BotoCoreError:
                logger.exception("sqs_consumer_manager_transient_error", queue=self.queue_name)
                await asyncio.sleep(self.error_sleep_seconds)
            except Exception:
                logger.exception("sqs_consumer_manager_fatal_error", queue=self.queue_name)
                raise

    async def _poll_continuous(self) -> None:
        while self.is_running:
            try:
                async with self.consumer.poll_raw_message() as ackable_msg:
                    if not ackable_msg:
                        await asyncio.sleep(self.poll_sleep_seconds)
                        continue

                    # Dispatch to the pure callback handler.
                    # A raised exception here means we skip the ack(),
                    # and it will be visible again in SQS after visibility timeout.
                    await self.handler(ackable_msg.payload)
                    await ackable_msg.ack()
            except asyncio.CancelledError:
                break
            except botocore.exceptions.ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code in (
                    "AWS.SimpleQueueService.NonExistentQueue",
                    "InvalidParameterValue",
                    "AccessDenied",
                ):
                    raise
                logger.exception("sqs_consumer_manager_poll_error", queue=self.queue_name)
                await asyncio.sleep(self.error_sleep_seconds)
            except botocore.exceptions.BotoCoreError:
                logger.exception("sqs_consumer_manager_poll_error", queue=self.queue_name)
                await asyncio.sleep(self.error_sleep_seconds)
            except Exception:
                logger.exception("sqs_consumer_manager_handler_error", queue=self.queue_name)
                # Do not sleep on handler errors, continue polling
