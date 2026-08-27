import asyncio
import contextlib
from typing import Any

import structlog
from notification.application.notification_compiler_use_case import NotificationCompilerUseCase
from notification.domain.models import NotificationEvent
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer

from notification_worker.adapters.inbound.jobs.notification_outbox_sweeper_job import (
    NotificationOutboxSweeperJobHandler,
)
from notification_worker.constants import NotificationJobName

logger = structlog.get_logger(__name__)


class NotificationEventSqsConsumer:
    def __init__(
        self,
        consumer: AwsSqsConsumer,
        notification_compiler: NotificationCompilerUseCase,
        cleanup_job_handler: NotificationOutboxSweeperJobHandler,
    ) -> None:
        self.consumer = consumer
        self.notification_compiler = notification_compiler
        self.cleanup_job_handler = cleanup_job_handler
        self._task: asyncio.Task[Any] | None = None
        self._shutdown_event = asyncio.Event()

    async def _process_message(self, body: dict[str, Any]) -> None:
        """
        Parses the incoming SQS payload (which matches the Outbox event payload)
        and passes it to the domain use case.
        """
        # Job-type messages (e.g. NOTIFICATION_OUTBOX_SWEEPER) are top-level envelopes
        # that do NOT contain an inner 'event' key. Route them before the event guard.
        top_level_event_type = body.get("event_type")
        if top_level_event_type == NotificationJobName.NOTIFICATION_OUTBOX_SWEEPER.value:
            logger.info("notification_sweeper_job_triggered")
            await self.cleanup_job_handler.execute()
            return

        # Notification dispatch messages wrap the event in the envelope payload:
        # {
        #   "event_type": "notification.requested",
        #   "payload": {
        #       "event": {
        #           "event_type": "invoice.failed",
        #           "payload": { ... },
        #           "tenant_id": "..."
        #       }
        #   }
        # }
        envelope_payload = body.get("payload")
        event_wrapper = envelope_payload.get("event") if envelope_payload else None
        if not event_wrapper:
            logger.error(
                "notification_sqs_message_missing_event_key",
                event_type=top_level_event_type,
                body_keys=list(body.keys()),
            )
            return

        payload = event_wrapper.get("payload")
        if not payload:
            logger.error(
                "notification_sqs_message_missing_payload_key",
                event_type=top_level_event_type,
            )
            return

        # Ensure tenant_id is available in the payload if not already there
        if "tenant_id" not in payload and "tenant_id" in event_wrapper:
            payload["tenant_id"] = event_wrapper["tenant_id"]

        domain_event_type = event_wrapper.get("event_type")

        # Validate required fields before constructing domain event
        tenant_id = payload.get("tenant_id")
        if not tenant_id:
            logger.error("SQS message payload missing 'tenant_id'")
            return
        if not domain_event_type:
            logger.error("SQS message payload missing 'event_type' / domain_event_type")
            return

        logger.info("notification_event_dispatching", domain_event_type=domain_event_type)

        notification_event = NotificationEvent(
            tenant_id=tenant_id, event_type=domain_event_type, data=payload
        )
        await self.notification_compiler.execute(notification_event)

    async def _run(self) -> None:
        logger.info("notification_event_sqs_consumer_started", queue_name=self.consumer.queue_name)

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
                logger.exception("notification_sqs_poll_loop_fatal_error")
                raise

        poll_task = asyncio.create_task(poll_loop())

        shutdown_task = asyncio.create_task(self._shutdown_event.wait())
        done, pending = await asyncio.wait(
            {poll_task, shutdown_task}, return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()

        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task

        if poll_task in done:
            await poll_task

    def start(self) -> asyncio.Task[Any]:
        if self._task is None:
            self._shutdown_event.clear()
            self._task = asyncio.create_task(self._run())
        return self._task

    async def stop(self) -> None:
        if self._task is not None:
            self._shutdown_event.set()
            # Wait for the task to fully complete before clearing the reference
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
