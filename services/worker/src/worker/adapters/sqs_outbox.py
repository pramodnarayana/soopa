import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aioboto3  # type: ignore[import-untyped]
from domain.events import MessageQueueName

from worker.core.errors import PermanentProvisioningError
from worker.ports.outbox import OutboxEvent, OutboxPort

logger = logging.getLogger(__name__)


class SqsEvent(OutboxEvent):
    def __init__(self, message_id: str, receipt_handle: str, body: dict[str, object]):
        self._message_id = message_id
        self.receipt_handle = receipt_handle
        self._body = body

    @property
    def id(self) -> str:
        return self._message_id

    @property
    def event_type(self) -> str:
        return str(self._body.get("event_type", "UNKNOWN"))

    @property
    def payload(self) -> dict[str, object]:
        payload_val = self._body.get("payload", {})
        if isinstance(payload_val, dict):
            return payload_val
        return {}


class SqsOutboxAdapter(OutboxPort):
    def __init__(self, queue_name: str = MessageQueueName.PROVISIONING):
        self.queue_name = queue_name
        self.endpoint_url = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
        self.region = "us-east-1"
        self.session = aioboto3.Session()

    @asynccontextmanager
    async def process_next_event(self) -> AsyncIterator[OutboxEvent | None]:
        async with self.session.client(
            "sqs", endpoint_url=self.endpoint_url, region_name=self.region
        ) as sqs:
            try:
                queue_url_response = await sqs.get_queue_url(QueueName=self.queue_name)
                queue_url = queue_url_response["QueueUrl"]
            except Exception as e:
                logger.error(f"Failed to get queue URL for {self.queue_name}: {e}")
                yield None
                return

            response = await sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=5,
            )

            messages = response.get("Messages", [])
            if not messages:
                yield None
                return

            msg = messages[0]
            receipt_handle = msg["ReceiptHandle"]
            message_id = msg["MessageId"]
            body_str = msg.get("Body", "{}")

            try:
                body = json.loads(body_str)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON body from SQS message {message_id}")
                await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                yield None
                return

            event = SqsEvent(message_id=message_id, receipt_handle=receipt_handle, body=body)

            try:
                yield event
                # Delete the message on success
                await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                logger.info(f"Successfully processed and deleted SQS message {message_id}")
            except Exception as e:
                if isinstance(e, PermanentProvisioningError):
                    logger.error(
                        f"Permanent error processing event {event.id}: {e}. Removing from queue."
                    )
                    await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                else:
                    logger.exception(
                        f"Transient error processing event {event.id}: {e}. Leaving on queue."
                    )
