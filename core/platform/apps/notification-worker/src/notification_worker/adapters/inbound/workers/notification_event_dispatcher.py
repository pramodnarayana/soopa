import structlog
from notification.application.notification_compiler_use_case import (
    CompileNotificationCommand,
    NotificationCompilerUseCase,
)
from notification.domain.constants import NotificationEventType
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

        if top_level_event_type != NotificationEventType.NOTIFICATION_TRIGGERED.value:
            logger.error(
                "notification_sqs_message_unsupported_event_type",
                event_type=top_level_event_type,
            )
            return

        # Notification dispatch messages wrap the domain event in the envelope payload:
        # {
        #   "event_type": "notification.triggered",
        #   "tenant_id": "...",
        #   "payload": {
        #       "notification_type": "invoice.failed",
        #       "notification_data": { ... }
        #   }
        # }
        top_level_tenant_id = body.get("tenant_id")
        raw_envelope_payload = body.get("payload")
        if not isinstance(raw_envelope_payload, dict):
            logger.error(
                "notification_sqs_message_invalid_payload",
                event_type=top_level_event_type,
                body_keys=list(body.keys()),
            )
            return
        envelope_payload = raw_envelope_payload

        raw_data = envelope_payload.get("notification_data")
        if not isinstance(raw_data, dict):
            logger.error(
                "notification_sqs_message_missing_notification_data_key",
                event_type=top_level_event_type,
            )
            return
        payload = raw_data

        # Ensure tenant_id is available in the payload if not already there
        if "tenant_id" not in payload and isinstance(top_level_tenant_id, str):
            payload["tenant_id"] = top_level_tenant_id

        domain_event_type = envelope_payload.get("notification_type")

        # Validate required fields before constructing domain event
        tenant_id = payload.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id:
            logger.error("SQS message payload missing 'tenant_id'")
            return
        if not isinstance(domain_event_type, str) or not domain_event_type:
            logger.error("SQS message payload missing 'event_type' / domain_event_type")
            return

        logger.info("notification_event_dispatching", domain_event_type=domain_event_type)

        notification_event = CompileNotificationCommand(
            tenant_id=tenant_id,
            event_type=domain_event_type,
            data=payload,
        )
        await self.notification_compiler.execute(notification_event)
