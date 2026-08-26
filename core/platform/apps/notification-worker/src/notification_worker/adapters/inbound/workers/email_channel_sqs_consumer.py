import asyncio
import contextlib
from typing import Any

import structlog
from notification.adapters.outbound.channels import EmailDeliveryStrategy
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer

logger = structlog.get_logger(__name__)


class EmailChannelSqsConsumer:
    def __init__(
        self,
        consumer: AwsSqsConsumer,
        email_strategy: EmailDeliveryStrategy,
    ) -> None:
        self.consumer = consumer
        self.email_strategy = email_strategy
        self._task: asyncio.Task[Any] | None = None
        self._shutdown_event = asyncio.Event()

    async def _process_message(self, body: dict[str, Any]) -> None:
        """
        Parses the incoming SQS payload for email delivery.
        """
        # The SQS poller uses poll_raw_message which parses the SNS Envelope
        # and yields the EventEnvelope as a dict.
        # body is equivalent to EventEnvelope as a dict.

        event_type = body.get("event_type")
        if event_type != "email.requested":
            logger.warning(
                "EmailChannelSqsConsumer received non-email event type",
                event_type=event_type,
            )
            return

        payload = body.get("payload")
        if not payload:
            logger.error("SQS message missing 'payload' key")
            return

        tenant_id = body.get("tenant_id")
        if not tenant_id:
            logger.error("SQS message payload missing 'tenant_id'")
            return

        content = payload.get("content")
        subject = payload.get("subject")
        data = payload.get("data", {})

        if not content:
            logger.error("SQS message payload missing 'content'")
            return

        logger.info(
            "Executing email delivery",
            tenant_id=tenant_id,
        )

        await self.email_strategy.deliver(
            tenant_id=tenant_id,
            content=content,
            subject=subject,
            data=data,
        )

    async def _run(self) -> None:
        logger.info("Starting EmailChannelSqsConsumer...", queue_name=self.consumer.queue_name)

        async def poll_loop() -> None:
            try:
                async with self.consumer as active_consumer:
                    while True:
                        async with active_consumer.poll_raw_message() as body:
                            if body:
                                await self._process_message(body)
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("SQS polling task exited with exception")
                raise

        poll_task = asyncio.create_task(poll_loop())

        shutdown_task = asyncio.create_task(self._shutdown_event.wait())
        done, pending = await asyncio.wait(
            {poll_task, shutdown_task}, return_when=asyncio.FIRST_COMPLETED
        )

        if poll_task in done:
            with contextlib.suppress(Exception):
                await poll_task

        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def start(self) -> asyncio.Task[Any]:
        if self._task is None:
            self._shutdown_event.clear()
            self._task = asyncio.create_task(self._run())
        return self._task

    async def stop(self) -> None:
        if self._task is not None:
            self._shutdown_event.set()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
