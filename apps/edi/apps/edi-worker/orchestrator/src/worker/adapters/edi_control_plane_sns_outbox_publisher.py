import json
from typing import Any, Self

import aioboto3
import structlog

from worker.ports.outbox_relay_publisher import OutboxRelayPublisherPort
from worker.ports.outbox_relay_repository import RelayOutboxEvent

logger = structlog.get_logger(__name__)


class EdiControlPlaneSnsOutboxPublisher(OutboxRelayPublisherPort):
    def __init__(self, topic_arn: str, endpoint_url: str | None = None, region: str = "us-east-1"):
        if not topic_arn:
            raise ValueError("sns_topic_arn_must_be_provided")
        self.topic_arn = topic_arn
        self.endpoint_url = endpoint_url
        self.region = region
        self.session = aioboto3.Session()
        self._sns_client: Any | None = None
        self._context_stack: Any | None = None

    async def __aenter__(self) -> Self:
        self._context_stack = self.session.client(
            "sns", endpoint_url=self.endpoint_url, region_name=self.region
        )
        self._sns_client = await self._context_stack.__aenter__()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any
    ) -> None:
        if self._context_stack:
            await self._context_stack.__aexit__(exc_type, exc_val, exc_tb)
        self._sns_client = None

    async def publish(self, event: RelayOutboxEvent) -> None:
        if not self._sns_client:
            raise RuntimeError("publish_must_be_called_within_context_manager")

        envelope = {
            "idempotencyKey": event.idempotency_key or event.id,
            "tenantId": event.tenant_id,
            "eventType": event.event_type,
            "payload": event.payload,
        }

        kwargs: dict[str, Any] = {
            "TopicArn": self.topic_arn,
            "Message": json.dumps(envelope),
        }

        if self.topic_arn.endswith(".fifo"):
            kwargs["MessageGroupId"] = event.tenant_id
            kwargs["MessageDeduplicationId"] = envelope["idempotencyKey"]

        await self._sns_client.publish(**kwargs)
        logger.debug("sns_event_published", event_type=event.event_type, topic_arn=self.topic_arn)
