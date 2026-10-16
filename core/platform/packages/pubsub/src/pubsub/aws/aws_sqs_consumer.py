import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, Protocol, cast

import aioboto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError
from pubsub.exceptions import ConsumerTerminalError, ConsumerTransientError
from pubsub.message import AckableMessage
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


class _SqsClientProtocol(Protocol):
    async def receive_message(self, **kwargs: Any) -> JsonDict: ...
    async def delete_message(self, **kwargs: Any) -> None: ...
    async def change_message_visibility(self, **kwargs: Any) -> None: ...


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
        wait_time_seconds: int = 20,
    ):
        if not queue_url:
            logger.error(
                "sqs_listener_missing_queue_url",
                message="SQS listener started without a queue URL",
            )
            raise ValueError("SQS queue URL must be provided")

        if not (0 <= wait_time_seconds <= 20):
            raise ValueError(
                f"wait_time_seconds must be between 0 and 20 (AWS SQS limit), got {wait_time_seconds}"
            )

        self.queue_url = queue_url
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self.wait_time_seconds = wait_time_seconds
        self.session = aioboto3.Session()
        self._client: _SqsClientProtocol | None = None
        self._client_context: Any | None = None

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
    def _extract_event_payload(body_str: str) -> JsonDict:
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

    async def _receive_single_message(self, sqs_client: _SqsClientProtocol) -> JsonDict | None:
        try:
            logger.debug("sqs_consumer_polling_started", queue_url=self.queue_url)
            response = await sqs_client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=self.wait_time_seconds,
                MessageAttributeNames=["All"],
            )

            messages = cast(list[JsonDict], response.get("Messages", []))
            if not messages:
                logger.debug("sqs_consumer_polling_empty", queue_url=self.queue_url)
                return None
            return messages[0]
        except ClientError as e:
            self._handle_client_error(e)
            return None
        except BotoCoreError as e:
            raise ConsumerTransientError(str(e)) from e

    async def _delete_message(self, sqs_client: _SqsClientProtocol, receipt_handle: str) -> None:
        try:
            await sqs_client.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)
        except ClientError as e:
            self._handle_client_error(e)
        except BotoCoreError as e:
            raise ConsumerTransientError(str(e)) from e

    @asynccontextmanager
    async def _process_with_client(
        self, sqs_client: _SqsClientProtocol
    ) -> AsyncGenerator[AckableMessage | None, None]:
        msg = await self._receive_single_message(sqs_client)
        if not msg:
            yield None
            return

        message_id = cast(str, msg.get("MessageId", ""))
        receipt_handle = cast(str, msg.get("ReceiptHandle", ""))
        body_str = cast(str, msg.get("Body", ""))

        logger.info(
            "sqs_consumer_received_raw_boto_message",
            queue_url=self.queue_url,
            message_id=message_id,
            body_length=len(body_str),
        )

        try:
            event_data = self._extract_event_payload(body_str)

            async def ack() -> None:
                await self._delete_message(sqs_client, receipt_handle)

            async def nack() -> None:
                try:
                    await sqs_client.change_message_visibility(
                        QueueUrl=self.queue_url,
                        ReceiptHandle=receipt_handle,
                        VisibilityTimeout=5,  # 5-second backoff
                    )
                except (ClientError, BotoCoreError) as e:
                    logger.warning("failed_to_reset_visibility_timeout", error=str(e))

            payload_dto = event_data

        except (json.JSONDecodeError, ValueError):
            logger.exception(
                "sqs_message_json_decode_failed",
                message_id=message_id,
                payload_length=len(body_str),
            )
            await self._delete_message(sqs_client, receipt_handle)
            yield None
            return

        yield AckableMessage(payload=payload_dto, ack=ack, nack=nack)
