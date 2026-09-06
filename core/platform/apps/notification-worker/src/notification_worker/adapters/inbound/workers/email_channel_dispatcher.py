from typing import cast

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

        tenant_id = cast(str | None, body.get("tenant_id"))
        if not tenant_id:
            logger.error("SQS message payload missing 'tenant_id'")
            return

        content = cast(str | None, payload.get("content"))
        subject = cast(str | None, payload.get("subject"))
        data = cast(JsonDict, payload.get("data", {}))

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
