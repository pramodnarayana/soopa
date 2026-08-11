import asyncio
import contextlib
import logging
import os
from typing import Any

from ..adapters.inbound.sqs_poller import poll_sqs_queue
from ..domain.models import NotificationEvent
from .dispatch_use_case import DispatchNotificationUseCase

logger = logging.getLogger(__name__)


class NotificationConsumerWorker:
    def __init__(self, dispatch_use_case: DispatchNotificationUseCase) -> None:
        self.dispatch_use_case = dispatch_use_case
        self._task: asyncio.Task[Any] | None = None
        self._shutdown_event = asyncio.Event()

    async def _process_message(self, body: dict[str, Any]) -> None:
        """
        Parses the incoming SQS payload (which matches the Outbox event payload)
        and passes it to the domain use case.
        """
        # The outbox CDC sweeper wraps the event in this envelope:
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

        logger.info(f"Dispatching notification event: {domain_event_type}")

        notification_event = NotificationEvent(
            tenant_id=payload["tenant_id"], event_type=domain_event_type, data=payload
        )
        await self.dispatch_use_case.execute(notification_event)

    async def _run(self) -> None:
        queue_name = "sqs-priority-notifications-queue"
        aws_endpoint = os.environ.get("AWS_ENDPOINT_URL")

        logger.info(f"Starting NotificationConsumerWorker for {queue_name}...")

        # We run the SQS poller in a task so we can cancel it via the shutdown event
        poll_task = asyncio.create_task(
            poll_sqs_queue(
                queue_name=queue_name,
                processor_func=self._process_message,
                aws_endpoint=aws_endpoint,
            )
        )

        await self._shutdown_event.wait()
        poll_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poll_task

    def start(self) -> asyncio.Task[Any]:
        if self._task is None:
            self._shutdown_event.clear()
            self._task = asyncio.create_task(self._run())
        return self._task

    def stop(self) -> None:
        if self._task is not None:
            self._shutdown_event.set()
            self._task = None
