import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aioboto3
import structlog

from worker.adapters.aws_types import SQSClientProtocol
from worker.ports.message_publisher import MessagePublisherPort, PublishMessageEnvelope

logger = structlog.get_logger(__name__)


class SqsPublisherAdapter(MessagePublisherPort):
    def __init__(self, endpoint_url: str | None = None, region: str = "us-east-1"):
        self.endpoint_url = endpoint_url
        self.region = region
        self.session = aioboto3.Session()
        self._queue_url_cache: dict[str, str] = {}
        self._sqs_client: SQSClientProtocol | None = None

    @asynccontextmanager
    async def connect(self) -> AsyncIterator["MessagePublisherPort"]:
        async with self.session.client(
            "sqs", endpoint_url=self.endpoint_url, region_name=self.region
        ) as sqs:
            self._sqs_client = sqs
            try:
                yield self
            finally:
                self._sqs_client = None

    async def _send_batch_chunk(
        self,
        queue_name: str,
        queue_url: str,
        sqs: SQSClientProtocol,
        batch: list[PublishMessageEnvelope],
    ) -> list[str]:
        entries = []
        for msg in batch:
            entry = {
                "Id": msg.message_id,
                "MessageBody": json.dumps(msg.event),
            }
            if queue_name.endswith(".fifo"):
                entry["MessageGroupId"] = msg.partition_key if msg.partition_key else "default"
                dedup_id = msg.idempotency_key or msg.message_id or str(uuid.uuid4())
                entry["MessageDeduplicationId"] = dedup_id
            entries.append(entry)

        if not entries:
            return []

        successful_ids = []
        try:
            resp = await sqs.send_message_batch(QueueUrl=queue_url, Entries=entries)
            for success in resp.get("Successful", []):
                successful_ids.append(success["Id"])
            for failed in resp.get("Failed", []):
                logger.error(
                    "Failed to forward message id={failed['Id']}: {failed['Message']}",
                    failedId=failed["Id"],
                    failedMessage=failed["Message"],
                )
        except Exception:
            logger.exception("Failed to send batch to {queue_name}", queue_name=queue_name)

        return successful_ids

    async def publish_batch(
        self, queue_name: str, messages: list[PublishMessageEnvelope]
    ) -> list[str]:
        if not messages:
            return []

        if self._sqs_client is None:
            raise RuntimeError("publish_batch must be called within the connect() context manager")

        sqs = self._sqs_client
        successful_ids = []

        if queue_name not in self._queue_url_cache:
            try:
                resp = await sqs.get_queue_url(QueueName=queue_name)
                self._queue_url_cache[queue_name] = resp["QueueUrl"]
            except Exception:
                logger.exception("Failed to get queue url for {queue_name}", queue_name=queue_name)
                return []

        queue_url = self._queue_url_cache[queue_name]

        # SQS allows max 10 messages per batch
        for i in range(0, len(messages), 10):
            batch = messages[i : i + 10]
            successful_ids.extend(await self._send_batch_chunk(queue_name, queue_url, sqs, batch))

        return successful_ids

    async def publish(self, queue_name: str, event: dict[str, Any]) -> None:
        """Publishes a single message without requiring the connect context manager."""
        if queue_name not in self._queue_url_cache:
            try:
                async with self.session.client(
                    "sqs", endpoint_url=self.endpoint_url, region_name=self.region
                ) as sqs:
                    resp = await sqs.get_queue_url(QueueName=queue_name)
                    self._queue_url_cache[queue_name] = resp["QueueUrl"]
            except Exception:
                logger.exception("Failed to get queue url for {queue_name}", queue_name=queue_name)
                raise

        queue_url = self._queue_url_cache[queue_name]

        try:
            async with self.session.client(
                "sqs", endpoint_url=self.endpoint_url, region_name=self.region
            ) as sqs:
                kwargs: dict[str, Any] = {
                    "QueueUrl": queue_url,
                    "MessageBody": json.dumps(event),
                }
                if queue_name.endswith(".fifo"):
                    partition_key = event.get("partition_key")
                    kwargs["MessageGroupId"] = partition_key if partition_key else "default"
                    idempotency_key = (
                        event.get("idempotency_key") or event.get("id") or str(uuid.uuid4())
                    )
                    kwargs["MessageDeduplicationId"] = idempotency_key

                await sqs.send_message(**kwargs)
        except Exception:
            logger.exception("Failed to send single message to {queue_name}", queue_name=queue_name)
            raise
