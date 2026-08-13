import json
import logging

import aioboto3

from ucp.domain.models.outbox_event import OutboxEvent
from ucp.ports.outbox_publisher import OutboxPublisherPort

logger = logging.getLogger(__name__)


class SnsOutboxPublisher(OutboxPublisherPort):
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
        self._client = None
        self._client_context = None

    async def __aenter__(self):
        """Allows using the publisher as a context manager for batch publishing."""
        if not self._client:
            self._client_context = self.session.client(
                "sns",
                region_name=self.region_name,
                endpoint_url=self.endpoint_url,
            )
            self._client = await self._client_context.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client_context:
            await self._client_context.__aexit__(exc_type, exc_val, exc_tb)
            self._client = None
            self._client_context = None

    async def publish(self, event: OutboxEvent) -> None:
        if not self.topic_arn:
            logger.warning("SNS Topic ARN not configured. Dropping event.")
            return

        message = {
            "eventId": event.id,
            "eventType": event.event_type,
            "tenantId": event.tenant_id,
            "payload": event.payload,
            "publishedAt": event.published_at.isoformat() if event.published_at else None,
        }

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
            logger.exception(f"Failed to publish event {event.id} to SNS")
            raise

    async def _publish_internal(self, sns_client, event: OutboxEvent, message: dict) -> None:
        await sns_client.publish(
            TopicArn=self.topic_arn,
            Message=json.dumps(message),
            MessageGroupId=event.tenant_id,  # Useful if SNS topic is FIFO
            MessageDeduplicationId=event.idempotency_key,
        )
        logger.debug(f"Successfully published {event.event_type} to SNS Topic {self.topic_arn}")
