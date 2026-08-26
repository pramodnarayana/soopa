import json
from typing import Any

import aioboto3
import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from platform_orm.events import EventEnvelope
from platform_orm.outbox_serializer import serialize_domain_event

logger = structlog.get_logger(__name__)


class AwsSnsPublisher(OutboxPublisherPort):
    """
    Generic Publisher that sends outbox events to an AWS SNS Topic.
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

    async def __aenter__(self) -> "AwsSnsPublisher":
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

    async def _publish_batch_internal(
        self, sns_client: Any, events: list[EventEnvelope], is_fifo: bool
    ) -> list[str]:
        successful_ids = []
        for i in range(0, len(events), 10):
            chunk = events[i : i + 10]
            entries = []
            entry_id_to_event_id = {}

            for idx, event in enumerate(chunk):
                entry_id = str(idx)
                entry_id_to_event_id[entry_id] = event.id
                message = serialize_domain_event(event)

                entry: dict[str, Any] = {
                    "Id": entry_id,
                    "Message": json.dumps(message),
                }
                if is_fifo:
                    entry["MessageGroupId"] = event.tenant_id or "default"
                    entry["MessageDeduplicationId"] = event.idempotency_key or event.id

                entries.append(entry)

            try:
                resp = await sns_client.publish_batch(
                    TopicArn=self.topic_arn, PublishBatchRequestEntries=entries
                )
                for success in resp.get("Successful", []):
                    successful_ids.append(entry_id_to_event_id[success["Id"]])
                for failed in resp.get("Failed", []):
                    logger.error(
                        "sns_batch_publish_entry_failed",
                        event_id=entry_id_to_event_id[failed["Id"]],
                        code=failed.get("Code"),
                        message=failed.get("Message"),
                    )
            except Exception:
                logger.exception("sns_batch_publish_chunk_failed", topic_arn=self.topic_arn)
        return successful_ids

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        if not self.topic_arn:
            raise ValueError("sns_topic_arn_not_configured")
        if not events:
            return []

        is_fifo = self.topic_arn.endswith(".fifo")
        try:
            if self._client:
                return await self._publish_batch_internal(self._client, events, is_fifo)

            async with self.session.client(
                "sns",
                region_name=self.region_name,
                endpoint_url=self.endpoint_url,
            ) as sns_client:
                return await self._publish_batch_internal(sns_client, events, is_fifo)
        except Exception:
            logger.exception("sns_publish_batch_failed", topic_arn=self.topic_arn)
            return []
