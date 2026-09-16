import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import aioboto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError
from pubsub.exceptions import ConsumerTerminalError, ConsumerTransientError
from pubsub.message import AckableMessage, SqsMessagePayload

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

    @staticmethod
    def _extract_event_payload(body_str: str) -> dict[str, Any]:
        """Parses the raw SQS body and unwraps the SNS envelope if present."""
        raw_body = json.loads(body_str)

        if (
            isinstance(raw_body, dict)
            and raw_body.get("Type") == "Notification"
            and "Message" in raw_body
        ):
            unwrapped = json.loads(raw_body["Message"])
            if not isinstance(unwrapped, dict):
                raise ValueError("Unwrapped SNS payload is not a JSON object")
            return unwrapped

        if not isinstance(raw_body, dict):
            raise TypeError("SQS payload is not a JSON object")

        return raw_body

    @staticmethod
    def _handle_client_error(e: ClientError) -> None:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in (
            "AWS.SimpleQueueService.NonExistentQueue",
            "InvalidParameterValue",
            "AccessDenied",
        ):
            raise ConsumerTerminalError(str(e)) from e
        raise ConsumerTransientError(str(e)) from e

    async def _receive_single_message(self, sqs_client: Any) -> dict[str, Any] | None:
        try:
            logger.debug("sqs_consumer_polling_started", queue_url=self.queue_url)
            response = await sqs_client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=5,
            )
            messages = cast(list[dict[str, Any]], response.get("Messages", []))
            if not messages:
                logger.debug("sqs_consumer_polling_empty", queue_url=self.queue_url)
                return None
            return messages[0]
        except ClientError as e:
            self._handle_client_error(e)
            return None
        except BotoCoreError as e:
            raise ConsumerTransientError(str(e)) from e

    async def _delete_message(self, sqs_client: Any, receipt_handle: str) -> None:
        try:
            await sqs_client.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)
        except ClientError as e:
            self._handle_client_error(e)
        except BotoCoreError as e:
            raise ConsumerTransientError(str(e)) from e

    @asynccontextmanager
    async def _process_with_client(
        self, sqs_client: Any
    ) -> AsyncGenerator[AckableMessage | None, None]:
        msg = await self._receive_single_message(sqs_client)
        if not msg:
            yield None
            return

        message_id = msg["MessageId"]
        receipt_handle = msg["ReceiptHandle"]
        body_str = msg["Body"]

        logger.info(
            "sqs_consumer_received_raw_boto_message",
            queue_url=self.queue_url,
            message_id=message_id,
            body_length=len(body_str),
        )

        yielded = False
        try:
            event_data = self._extract_event_payload(body_str)

            async def ack() -> None:
                await self._delete_message(sqs_client, receipt_handle)

            async def nack() -> None:
                pass

            yielded = True

            payload_dto = SqsMessagePayload(
                idempotency_key=event_data.get("idempotency_key"),
                tenant_id=event_data.get("tenant_id"),
                event_type=event_data.get("event_type"),
                raw_data=event_data,
            )

            # Yield the ackable message
            yield AckableMessage(payload=payload_dto, ack=ack, nack=nack)

        except (json.JSONDecodeError, ValueError):
            logger.exception(
                "sqs_message_json_decode_failed",
                message_id=message_id,
                payload_length=len(body_str),
            )
            await self._delete_message(sqs_client, receipt_handle)
            if not yielded:
                yield None
        except Exception as e:
            # We MUST raise the exception to satisfy the 'No Silenced Failures' enterprise rule.
            # The upstream consumer manager is responsible for catching and handling this properly.
            logger.exception(
                "sqs_event_processing_failed",
                message_id=message_id,
                error=str(e),
            )
            if not yielded:
                yield None
            raise
