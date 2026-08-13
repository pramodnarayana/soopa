import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import aioboto3
import structlog
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from ...ports.ucp_event_listener import UcpEventListenerPort, UcpEventMessage

logger = structlog.get_logger(__name__)


class SqsUcpEventListener(UcpEventListenerPort):
    """
    AWS SQS Adapter for consuming UCP events from a queue.
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
        self._client = None
        self._client_context = None

    async def __aenter__(self):
        """Allows using the listener as a context manager for continuous polling with connection reuse."""
        if not self._client:
            self._client_context = self.session.client(
                "sqs",
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

    @asynccontextmanager
    async def process_next_event(self) -> AsyncGenerator[UcpEventMessage | None, None]:
        if not self.queue_url:
            yield None
            return

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

    @asynccontextmanager
    async def _process_with_client(
        self, sqs_client
    ) -> AsyncGenerator[UcpEventMessage | None, None]:
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

                event_message = UcpEventMessage.model_validate(event_data)

                # Yield the message to the pure business logic
                yield event_message

                # If we return here without exception, the business logic succeeded.
                await sqs_client.delete_message(
                    QueueUrl=self.queue_url, ReceiptHandle=receipt_handle
                )

            except json.JSONDecodeError:
                logger.exception(
                    "sqs_message_json_decode_failed", message_id=message_id, payload_length=len(body_str)
                )
                await sqs_client.delete_message(
                    QueueUrl=self.queue_url, ReceiptHandle=receipt_handle
                )
                yield None
            except Exception:
                logger.exception("ucp_event_processing_failed", message_id=message_id)
                raise

        except ClientError:
            logger.exception("sqs_client_error")
            raise
