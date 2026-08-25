import json
from typing import Any

import aioboto3
import structlog
from platform_orm.events import EventEnvelope
from platform_orm.outbox_serializer import serialize_domain_event

from ucp.ports.outbound.outbox_publisher_port import OutboxPublisherPort

logger = structlog.get_logger(__name__)


class UcpOutboxSnsPublisher(OutboxPublisherPort):
    """
    Publishes outbox events to an AWS SNS Topic (Global Bus).
    """

    def __init__(
        self,
        topic_arn: str,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
    ):
        self.topic_arn = topic_arn
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self.session = aioboto3.Session()
        self._client: Any = None
        self._client_context: Any = None

    async def __aenter__(self) -> "UcpOutboxSnsPublisher":
        """Allows using the publisher as a context manager for batch publishing."""
        if not self._client:
            self._client_context = self.session.client(
                "sns",
                region_name=self.region_name,
                endpoint_url=self.endpoint_url,
            )
            self._client = await self._client_context.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._client_context:
            await self._client_context.__aexit__(exc_type, exc_val, exc_tb)
            self._client = None
            self._client_context = None

    async def publish(self, event: EventEnvelope) -> None:
        if not self.topic_arn:
            raise ValueError("sns_topic_arn_not_configured")

        # Serializes the EventEnvelope exactly as defined in core/platform
        message = serialize_domain_event(event)

        try:
            # If used outside a context manager, create a one-off client.
            # If used inside a context manager, reuse the persistent client.
            if self._client:
                sns_client = self._client
                await self._publish_internal(sns_client, event, message)
            else:
                async with self.session.client(
                    "sns",
                    region_name=self.region_name,
                    endpoint_url=self.endpoint_url,
                ) as sns_client:
                    await self._publish_internal(sns_client, event, message)
        except Exception:
            logger.exception("sns_publish_failed", event_id=event.id)
            raise

    async def _publish_internal(
        self, sns_client: Any, event: EventEnvelope, message: dict[str, Any]
    ) -> None:
        publish_params: dict[str, Any] = {
            "TopicArn": self.topic_arn,
            "Message": json.dumps(message),
        }
        # Only include FIFO-specific parameters if the topic is FIFO
        if self.topic_arn.endswith(".fifo"):
            publish_params["MessageGroupId"] = event.tenant_id or "default"
            publish_params["MessageDeduplicationId"] = event.idempotency_key or event.id

        await sns_client.publish(**publish_params)
        logger.debug("sns_event_published", event_type=event.event_type, topic_arn=self.topic_arn)
