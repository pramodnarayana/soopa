from collections.abc import Mapping

import structlog
from notification.domain.constants import NotificationEventType
from notification.ports.outbound.notification_channel_strategy_port import DeliveryStrategyPort
from seedwork.domain.types import JsonDict, JsonValue

logger = structlog.get_logger(__name__)


class EmailChannelDispatcher:
    def __init__(
        self,
        email_strategy: DeliveryStrategyPort,
    ) -> None:
        self.email_strategy = email_strategy

    async def dispatch_raw(self, body: Mapping[str, JsonValue]) -> None:
        """
        Parses the incoming SQS payload for email delivery.
        """
        if not isinstance(body, dict):
            logger.error("email_channel_sqs_message_invalid_body", body_type=type(body).__name__)
            return

        event_type = body.get("event_type")
        if event_type != NotificationEventType.EMAIL_REQUESTED:
            logger.error(
                "email_channel_sqs_message_unsupported_event_type",
                event_type=event_type,
            )
            return

        raw_payload = body.get("payload")
        if not isinstance(raw_payload, dict):
            logger.error(
                "email_channel_sqs_message_invalid_payload",
                event_type=event_type,
                body_keys=list(body.keys()),
            )
            return
        payload: dict[str, JsonValue] = raw_payload

        tenant_id = body.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id:
            logger.error(
                "email_channel_sqs_message_missing_tenant_id",
                event_type=event_type,
            )
            return

        content = payload.get("content")
        if not isinstance(content, str) or not content:
            logger.error(
                "email_channel_sqs_message_missing_content",
                tenant_id=tenant_id,
            )
            return

        subject = payload.get("subject")
        if subject is not None and not isinstance(subject, str):
            logger.error(
                "email_channel_sqs_message_invalid_subject",
                tenant_id=tenant_id,
            )
            return

        data = payload.get("data", {})
        if not isinstance(data, dict):
            logger.error(
                "email_channel_sqs_message_invalid_data",
                tenant_id=tenant_id,
            )
            return

        logger.info(
            "email_channel_delivery_executing",
            tenant_id=tenant_id,
        )

        delivery_data: JsonDict = {str(k): v for k, v in data.items()}
        await self.email_strategy.deliver(
            tenant_id=tenant_id,
            content=content,
            subject=subject,
            data=delivery_data,
        )

        logger.info(
            "email_channel_delivery_completed",
            tenant_id=tenant_id,
        )
