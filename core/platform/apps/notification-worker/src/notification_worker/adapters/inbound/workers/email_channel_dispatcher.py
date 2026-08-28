from typing import Any

import structlog
from notification.adapters.outbound.channels import EmailDeliveryStrategy

logger = structlog.get_logger(__name__)


class EmailChannelDispatcher:
    def __init__(
        self,
        email_strategy: EmailDeliveryStrategy,
    ) -> None:
        self.email_strategy = email_strategy

    async def dispatch_raw(self, body: dict[str, Any]) -> None:
        """
        Parses the incoming SQS payload for email delivery.
        """
        # The SQS poller uses poll_raw_message which parses the SNS Envelope
        # and yields the EventEnvelope as a dict.
        # body is equivalent to EventEnvelope as a dict.

        if not isinstance(body, dict):
            logger.error("SQS message body must be a dictionary")
            return

        event_type = body.get("event_type")
        if event_type != "email.requested":
            logger.warning(
                "EmailChannelSqsConsumer received non-email event type",
                event_type=event_type,
            )
            return

        payload = body.get("payload")
        if not payload or not isinstance(payload, dict):
            logger.error("SQS message missing 'payload' dictionary")
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
