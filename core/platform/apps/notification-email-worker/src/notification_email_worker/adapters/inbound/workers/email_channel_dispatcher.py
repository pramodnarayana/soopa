import structlog
from notification.adapters.outbound.channels import EmailChannelStrategy
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


class EmailChannelDispatcher:
    def __init__(
        self,
        email_strategy: EmailChannelStrategy,
    ) -> None:
        self.email_strategy = email_strategy

    async def dispatch_raw(self, body: JsonDict) -> None:
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

        raw_payload = body.get("payload")
        if not raw_payload:
            logger.error("SQS message missing 'payload' dictionary")
            return
        if not isinstance(raw_payload, dict):
            logger.error("SQS message 'payload' must be a dictionary")
            return
        payload = raw_payload

        tenant_id = body.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id:
            logger.error("SQS message payload must contain a non-empty string 'tenant_id'")
            return

        content = payload.get("content")
        if not isinstance(content, str) or not content:
            logger.error("SQS message payload must contain a non-empty string 'content'")
            return

        subject = payload.get("subject")
        if subject is not None and not isinstance(subject, str):
            logger.error("SQS message payload 'subject' must be a string when present")
            return

        data = payload.get("data", {})
        if not isinstance(data, dict):
            logger.error("SQS message payload 'data' must be a dictionary")
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
