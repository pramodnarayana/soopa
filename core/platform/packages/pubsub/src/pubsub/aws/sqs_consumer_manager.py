import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

import botocore.exceptions
import structlog
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer

logger = structlog.get_logger(__name__)


class SqsConsumerManager:
    """
    Centralized Message Pump for polling AWS SQS queues and dispatching
    to a pure python callback handler.

    This manages the background task lifecycle (while True loop), AWS connection sharing,
    message unwrapping, and deletion upon success.
    """

    def __init__(
        self,
        queue_name: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
        poll_sleep_seconds: float = 0.1,
        error_sleep_seconds: float = 5.0,
    ):
        self.queue_name = queue_name
        self.handler = handler
        self.poll_sleep_seconds = poll_sleep_seconds
        self.error_sleep_seconds = error_sleep_seconds

        self.is_running = False
        self._task: asyncio.Task[None] | None = None
        self.sqs_consumer = AwsSqsConsumer(
            queue_name=queue_name,
            region_name=region_name,
            endpoint_url=endpoint_url,
        )

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
                async with self.sqs_consumer:
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
                async with self.sqs_consumer.poll_raw_message() as ackable_msg:
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
