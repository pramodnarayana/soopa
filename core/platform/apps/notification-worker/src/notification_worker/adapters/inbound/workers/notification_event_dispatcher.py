from typing import cast

import structlog
from notification.application.notification_compiler_use_case import (
    CompileNotificationCommand,
    NotificationCompilerUseCase,
)
from seedwork.domain.types import JsonDict

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

    async def dispatch_raw(self, body: JsonDict) -> None:
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
        raw_envelope_payload = body.get("payload")
        if not isinstance(raw_envelope_payload, dict):
            logger.error(
                "notification_sqs_message_invalid_payload",
                event_type=top_level_event_type,
                body_keys=list(body.keys()),
            )
            return
        envelope_payload = raw_envelope_payload

        raw_event_wrapper = envelope_payload.get("event")
        if not isinstance(raw_event_wrapper, dict):
            logger.error(
                "notification_sqs_message_missing_event_key",
                event_type=top_level_event_type,
                body_keys=list(body.keys()),
            )
            return
        event_wrapper = raw_event_wrapper

        raw_payload = event_wrapper.get("payload")
        if not isinstance(raw_payload, dict):
            logger.error(
                "notification_sqs_message_missing_payload_key",
                event_type=top_level_event_type,
            )
            return
        payload = raw_payload

        # Ensure tenant_id is available in the payload if not already there
        if "tenant_id" not in payload and "tenant_id" in event_wrapper:
            payload["tenant_id"] = event_wrapper["tenant_id"]

        domain_event_type = cast(str | None, event_wrapper.get("event_type"))

        # Validate required fields before constructing domain event
        tenant_id = cast(str | None, payload.get("tenant_id"))
        if not tenant_id:
            logger.error("SQS message payload missing 'tenant_id'")
            return
        if not domain_event_type:
            logger.error("SQS message payload missing 'event_type' / domain_event_type")
            return

        logger.info("notification_event_dispatching", domain_event_type=domain_event_type)

        notification_event = CompileNotificationCommand(
            tenant_id=tenant_id,
            event_type=domain_event_type,
            data=payload,
        )
        await self.notification_compiler.execute(notification_event)
