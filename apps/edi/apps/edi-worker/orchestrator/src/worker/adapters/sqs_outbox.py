import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aioboto3

from worker.adapters.acl.registry import translate_external_event
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
    def body(self) -> dict[str, Any]:
        return self._body


class SqsOutboxAdapter(OutboxPort):
    def __init__(self, queue_name: str = "edi-tenant-sync.fifo"):
        self.queue_name = queue_name
        self.endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
        # Fallback for local development if missing
        if not self.endpoint_url and os.environ.get("ENVIRONMENT") == "local":
            self.endpoint_url = "http://localhost:4566"
        self.region = "us-east-1"
        self.session = aioboto3.Session()

    async def close(self) -> None:
        """Close the adapter and release all resources."""
        # aioboto3 sessions are lightweight and don't hold persistent connections
        # The session itself doesn't need explicit cleanup, but we provide this
        # method for interface consistency with other adapters
        logger.info("Closed SqsOutboxAdapter resources")

    @asynccontextmanager
    async def process_next_event(self) -> AsyncIterator[OutboxEvent | None]:
        async with self.session.client(
            "sqs", endpoint_url=self.endpoint_url, region_name=self.region
        ) as sqs:
            try:
                queue_url_response = await sqs.get_queue_url(QueueName=self.queue_name)
                queue_url = queue_url_response["QueueUrl"]
            except Exception:
                logger.exception(f"Failed to get queue URL for {self.queue_name}")

                yield None
                return

            response = await sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=5,
            )

            logger.debug(
                f"SQS receive_message: {len(response.get('Messages', []))} message(s) received"
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
                raw_body = json.loads(body_str)
                # Handle SNS Envelope
                if (
                    "Type" in raw_body
                    and raw_body["Type"] == "Notification"
                    and "Message" in raw_body
                ):
                    body = json.loads(raw_body["Message"])
                else:
                    body = raw_body

                # Anti-Corruption Layer (ACL): Translate UCP external events to EDI internal domain events
                external_event_type = body.get("eventType")
                if external_event_type:
                    try:
                        translated_body = translate_external_event(external_event_type, body)
                        if translated_body is None:
                            # Unregistered event type - leave message for retry/DLQ
                            logger.warning(
                                f"Unregistered event type '{external_event_type}' in message {message_id}. "
                                f"Leaving message for retry or DLQ routing."
                            )
                            yield None
                            return
                        body = translated_body
                    except ValueError:
                        # Permanent validation error - malformed message
                        logger.exception(
                            "Permanent validation error for event type '%s' in message %s. "
                            "Message body: %s. Deleting malformed message.",
                            external_event_type,
                            message_id,
                            body,
                        )
                        await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                        yield None
                        return
            except json.JSONDecodeError:
                logger.exception(f"Failed to parse JSON body from SQS message {message_id}")
                await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                yield None
                return

            event = SqsEvent(message_id=message_id, receipt_handle=receipt_handle, body=body)
            logger.info(f"Picked up SQS event {message_id}")

            try:
                yield event
                # Delete the message on success
                await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                logger.info(f"Successfully processed and deleted SQS message {message_id}")
            except Exception as e:
                if isinstance(e, PermanentProvisioningError):
                    logger.exception(
                        "Permanent error processing event %s. Removing from queue.", event.id
                    )
                    await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                else:
                    logger.exception(
                        "Transient error processing event %s. Leaving on queue.", event.id
                    )
                raise

    async def publish_event(
        self,
        event_type: str,
        payload: dict[str, object],
        idempotency_key: str,
        tenant_id: str,
    ) -> None:
        """Publishes an event to the outbox queue."""
        async with self.session.client(
            "sqs", endpoint_url=self.endpoint_url, region_name=self.region
        ) as sqs:
            try:
                queue_url_response = await sqs.get_queue_url(QueueName=self.queue_name)
                queue_url = queue_url_response["QueueUrl"]
            except Exception:
                logger.exception(f"Failed to get queue URL for {self.queue_name}")

                raise

            message_body = json.dumps(
                {
                    **(payload or {}),
                    "tenant_id": tenant_id,
                    "event_type": event_type,
                    "idempotency_key": idempotency_key,
                }
            )

            await sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=message_body,
                MessageGroupId=tenant_id,
                MessageDeduplicationId=idempotency_key,
            )
            logger.info(f"Published event {event_type} for tenant {tenant_id} to {self.queue_name}")
