import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import aioboto3
import structlog
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from identity_worker.ports.inbound.identity_event_consumer_port import (
    IdentityEventConsumerPort,
    IdentityEventMessage,
)

logger = structlog.get_logger(__name__)


class IdentityEventSqsConsumer(IdentityEventConsumerPort):
    """
    AWS SQS Adapter for consuming Identity events from a queue.
    """

    def __init__(
        self,
        queue_name: str,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
    ):
        if not queue_name:
            logger.error(
                "sqs_listener_missing_queue_name",
                message="SQS Listener started without a Queue Name! Please set SQS_IDENTITY_SYNC_QUEUE_NAME in your .env",
            )
            raise ValueError("SQS Queue Name must be provided to IdentityEventSqsConsumer")

        self.queue_name = queue_name
        self._queue_url: str | None = None
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self.session = aioboto3.Session()
        self._client: Any = None
        self._client_context: Any = None

    async def __aenter__(self) -> "IdentityEventSqsConsumer":
        """Allows using the listener as a context manager for continuous polling with connection reuse."""
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

    @asynccontextmanager
    async def process_next_event(self) -> AsyncGenerator[IdentityEventMessage | None, None]:
        # Use shared client if available, else create one-off
        if self._client:
            sqs_client = self._client
            async with self._process_with_client(sqs_client) as event:
                yield event
        else:
            async with (
                self.session.client(
                    "sqs",
                    region_name=self.region_name,
                    endpoint_url=self.endpoint_url,
                ) as sqs_client,
                self._process_with_client(sqs_client) as event,
            ):
                yield event

    async def _get_queue_url(self, sqs_client: Any) -> str:
        if self._queue_url:
            return self._queue_url
        try:
            resp = await sqs_client.get_queue_url(QueueName=self.queue_name)
            self._queue_url = resp["QueueUrl"]
            return self._queue_url
        except Exception:
            logger.exception("sqs_queue_url_resolution_failed", queue_name=self.queue_name)
            raise

    @asynccontextmanager
    async def _process_with_client(
        self, sqs_client: Any
    ) -> AsyncGenerator[IdentityEventMessage | None, None]:
        try:
            queue_url = await self._get_queue_url(sqs_client)
            response = await sqs_client.receive_message(
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
            body_str = msg["Body"]

            yielded = False
            event_data: Any = {}
            try:
                raw_body = json.loads(body_str)
                # Handle SNS Envelope
                if (
                    "Type" in raw_body
                    and raw_body["Type"] == "Notification"
                    and "Message" in raw_body
                ):
                    event_data = json.loads(raw_body["Message"])
                else:
                    event_data = raw_body

                event_message = IdentityEventMessage.model_validate(event_data)

                yielded = True
                # Yield the message to the pure business logic
                yield event_message

                # If we return here without exception, the business logic succeeded.
                await sqs_client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)

            except json.JSONDecodeError:
                logger.exception(
                    "sqs_message_json_decode_failed",
                    message_id=message_id,
                    payload_length=len(body_str),
                )
                if yielded:
                    raise
                yield None
            except Exception as e:
                event_type = (
                    event_data.get("event_type", "unknown")
                    if isinstance(event_data, dict)
                    else "unknown"
                )
                logger.exception(
                    "identity_event_processing_failed",
                    message_id=message_id,
                    error=str(e),
                    event_type=event_type,
                )
                if yielded:
                    raise
                yield None

        except ClientError:
            logger.exception("sqs_client_error")
            raise
