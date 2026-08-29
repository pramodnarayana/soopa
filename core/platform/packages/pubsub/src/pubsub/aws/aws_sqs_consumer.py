import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import aioboto3
import structlog
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from pubsub.message import AckableMessage

logger = structlog.get_logger(__name__)


class AwsSqsConsumer:
    """
    Generic AWS SQS Adapter for long-polling messages from a queue.
    Handles aioboto3 session pooling, SNS envelope unwrapping, and batch deletion.
    """

    def __init__(
        self,
        queue_url: str,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
    ):
        if not queue_url:
            logger.error(
                "sqs_listener_missing_queue_url",
                message="SQS listener started without a queue URL",
            )
            raise ValueError("SQS queue URL must be provided")

        self.queue_url = queue_url
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self.session = aioboto3.Session()
        self._client: Any = None
        self._client_context: Any = None

    async def __aenter__(self) -> "AwsSqsConsumer":
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
    async def poll_raw_message(self) -> AsyncGenerator[AckableMessage | None, None]:
        # Use shared client if available, else create one-off
        if self._client:
            async with self._process_with_client(self._client) as event:
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

    @asynccontextmanager
    async def _process_with_client(
        self, sqs_client: Any
    ) -> AsyncGenerator[AckableMessage | None, None]:
        try:
            response = await sqs_client.receive_message(
                QueueUrl=self.queue_url,
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
            event_data: dict[str, Any] = {}
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

                async def ack() -> None:
                    await sqs_client.delete_message(
                        QueueUrl=self.queue_url, ReceiptHandle=receipt_handle
                    )

                async def nack() -> None:
                    pass

                yielded = True
                # Yield the ackable message
                yield AckableMessage(payload=event_data, ack=ack, nack=nack)

            except json.JSONDecodeError:
                logger.exception(
                    "sqs_message_json_decode_failed",
                    message_id=message_id,
                    payload_length=len(body_str),
                )
                await sqs_client.delete_message(
                    QueueUrl=self.queue_url, ReceiptHandle=receipt_handle
                )
                if not yielded:
                    yield None
            except Exception as e:
                # Log the error but DO NOT raise. If we raise, it crashes the polling loop.
                # By swallowing it here, we ensure the message is NOT deleted (so SQS will retry it later),
                # but the worker can immediately continue polling the next message.
                event_type = (
                    event_data.get("event_type", "unknown")
                    if isinstance(event_data, dict)
                    else "unknown"
                )
                logger.exception(
                    "sqs_event_processing_failed",
                    message_id=message_id,
                    error=str(e),
                    event_type=event_type,
                )
                if not yielded:
                    yield None

        except ClientError:
            logger.exception("sqs_client_error")
            raise
