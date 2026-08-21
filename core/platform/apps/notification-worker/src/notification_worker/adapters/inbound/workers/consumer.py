import asyncio
import contextlib
import os
from typing import Any

import structlog
from notification.application.dispatch_use_case import DispatchNotificationUseCase
from notification.domain.models import NotificationEvent

from .sqs_poller import poll_sqs_queue

logger = structlog.get_logger(__name__)


from ..jobs.notification_outbox_sweeper_job import (
    NotificationOutboxSweeperJob,
)


class NotificationConsumerWorker:
    def __init__(
        self,
        dispatch_use_case: DispatchNotificationUseCase,
        cleanup_job_handler: NotificationOutboxSweeperJob,
    ) -> None:
        self.dispatch_use_case = dispatch_use_case
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
        if top_level_event_type == "NOTIFICATION_OUTBOX_SWEEPER":
            logger.info("Received sweeper job payload, triggering outbox sweep.")
            await self.cleanup_job_handler.execute()
            return

        # Notification dispatch messages wrap the event in this envelope:
        # {
        #   "event": {
        #       "payload": { ... },
        #       "tenant_id": "..."
        #   },
        #   "event_type": "notification.triggered", ...
        # }
        event_wrapper = body.get("event")
        if not event_wrapper:
            logger.error("SQS message missing 'event' key")
            return

        payload = event_wrapper.get("payload")
        if not payload:
            logger.error("SQS message 'event' missing 'payload' key")
            return

        # Ensure tenant_id is available in the payload if not already there
        if "tenant_id" not in payload and "tenant_id" in event_wrapper:
            payload["tenant_id"] = event_wrapper["tenant_id"]

        # Extract the true domain event type (e.g. "invoice.failed") if it was wrapped
        # inside a "notification.triggered" routing envelope.
        domain_event_type = payload.get("event_type", body.get("event_type"))

        # Validate required fields before constructing domain event
        tenant_id = payload.get("tenant_id")
        if not tenant_id:
            logger.error("SQS message payload missing 'tenant_id'")
            return
        if not domain_event_type:
            logger.error("SQS message payload missing 'event_type' / domain_event_type")
            return

        logger.info(
            "Dispatching notification event: {domain_event_type}",
            domain_event_type=domain_event_type,
        )

        notification_event = NotificationEvent(
            tenant_id=tenant_id, event_type=domain_event_type, data=payload
        )
        await self.dispatch_use_case.execute(notification_event)

    async def _run(self) -> None:
        queue_name = "PriorityNotificationsQueue"
        aws_endpoint = os.environ.get("AWS_ENDPOINT_URL")

        logger.info(
            "Starting NotificationConsumerWorker for {queue_name}...", queue_name=queue_name
        )

        # We run the SQS poller in a task so we can cancel it via the shutdown event
        poll_task = asyncio.create_task(
            poll_sqs_queue(
                queue_name=queue_name,
                processor_func=self._process_message,
                aws_endpoint=aws_endpoint,
            )
        )

        # Wait for whichever completes first: polling task or shutdown signal
        shutdown_task = asyncio.create_task(self._shutdown_event.wait())
        done, pending = await asyncio.wait(
            {poll_task, shutdown_task}, return_when=asyncio.FIRST_COMPLETED
        )

        # If polling task completed first (possibly with exception), log/propagate it
        if poll_task in done:
            try:
                await poll_task  # Re-raise exception if any
            except Exception:
                logger.exception("SQS polling task exited with exception")
                raise

        # Cancel whichever task is still pending
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
            # Wait for the task to fully complete before clearing the reference
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
