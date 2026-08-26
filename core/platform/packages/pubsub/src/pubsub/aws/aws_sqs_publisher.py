import json
from typing import Any

import aioboto3
import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from platform_orm.events import EventEnvelope
from platform_orm.outbox_serializer import serialize_domain_event

logger = structlog.get_logger(__name__)


class AwsSqsPublisher(OutboxPublisherPort):
    """
    Generic Publisher that sends outbox events to an AWS SQS Queue.
    """

    def __init__(
        self,
        queue_url: str,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
    ):
        self.queue_url = queue_url
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self.session = aioboto3.Session()
        self._client: Any = None
        self._client_context: Any = None

    async def __aenter__(self) -> "AwsSqsPublisher":
        """Allows using the publisher as a context manager for batch publishing."""
        if not self._client:
            self._client_context = self.session.client(
                "sqs",
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
        if not self.queue_url:
            raise ValueError("sqs_queue_url_not_configured")

        message = serialize_domain_event(event)

        try:
            if self._client:
                sqs_client = self._client
                await self._publish_internal(sqs_client, event, message)
            else:
                async with self.session.client(
                    "sqs",
                    region_name=self.region_name,
                    endpoint_url=self.endpoint_url,
                ) as sqs_client:
                    await self._publish_internal(sqs_client, event, message)
        except Exception:
            logger.exception("sqs_publish_failed", event_id=event.id)
            raise

    async def _publish_internal(
        self, sqs_client: Any, event: EventEnvelope, message: dict[str, Any]
    ) -> None:
        publish_params: dict[str, Any] = {
            "QueueUrl": self.queue_url,
            "MessageBody": json.dumps(message),
        }

        if self.queue_url.endswith(".fifo"):
            publish_params["MessageGroupId"] = event.tenant_id or "default"
            publish_params["MessageDeduplicationId"] = event.idempotency_key or event.id

        await sqs_client.send_message(**publish_params)
        logger.debug("sqs_event_published", event_type=event.event_type, queue_url=self.queue_url)

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        if not self.queue_url:
            raise ValueError("sqs_queue_url_not_configured")

        if not events:
            return []

        successful_ids: list[str] = []
        is_fifo = self.queue_url.endswith(".fifo")

        try:
            if self._client:
                await self._do_publish_batch(self._client, events, is_fifo, successful_ids)
            else:
                async with self.session.client(
                    "sqs",
                    region_name=self.region_name,
                    endpoint_url=self.endpoint_url,
                ) as sqs_client:
                    await self._do_publish_batch(sqs_client, events, is_fifo, successful_ids)
        except Exception:
            logger.exception("sqs_publish_batch_failed", queue_url=self.queue_url)

        return successful_ids

    async def _do_publish_batch(
        self, sqs_client: Any, events: list[EventEnvelope], is_fifo: bool, successful_ids: list[str]
    ) -> None:
        # SQS supports a maximum of 10 messages per batch
        for i in range(0, len(events), 10):
            chunk = events[i : i + 10]
            await self._publish_chunk(sqs_client, chunk, is_fifo, successful_ids)

    async def _publish_chunk(
        self, sqs_client: Any, chunk: list[EventEnvelope], is_fifo: bool, successful_ids: list[str]
    ) -> None:
        entries = []
        entry_id_to_event_id = {}

        for idx, event in enumerate(chunk):
            entry_id = str(idx)
            entry_id_to_event_id[entry_id] = event.id
            message = serialize_domain_event(event)

            entry: dict[str, Any] = {
                "Id": entry_id,
                "MessageBody": json.dumps(message),
            }
            if is_fifo:
                entry["MessageGroupId"] = event.tenant_id or "default"
                entry["MessageDeduplicationId"] = event.idempotency_key or event.id

            entries.append(entry)

        try:
            resp = await sqs_client.send_message_batch(QueueUrl=self.queue_url, Entries=entries)

            for success in resp.get("Successful", []):
                successful_ids.append(entry_id_to_event_id[success["Id"]])

            for failed in resp.get("Failed", []):
                logger.error(
                    "sqs_batch_publish_entry_failed",
                    event_id=entry_id_to_event_id[failed["Id"]],
                    code=failed.get("Code"),
                    message=failed.get("Message"),
                )
        except Exception:
            logger.exception("sqs_batch_publish_chunk_failed", queue_url=self.queue_url)
