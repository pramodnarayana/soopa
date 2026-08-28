from typing import Any

import structlog
from notification.application.notification_compiler_use_case import NotificationCompilerUseCase
from notification.domain.models import NotificationEvent

from notification_worker.adapters.inbound.jobs.notification_outbox_sweeper_job import (
    NotificationOutboxSweeperJobHandler,
)
from notification_worker.constants import NotificationJobName

logger = structlog.get_logger(__name__)


class NotificationEventDispatcher:
    def __init__(
        self,
        notification_compiler: NotificationCompilerUseCase,
        cleanup_job_handler: NotificationOutboxSweeperJobHandler,
    ) -> None:
        self.notification_compiler = notification_compiler
        self.cleanup_job_handler = cleanup_job_handler

    async def dispatch_raw(self, body: dict[str, Any]) -> None:
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
