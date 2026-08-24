import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any

import aioboto3
import structlog

from worker.adapters.acl.registry import translate_external_event
from worker.adapters.aws_types import SQSClientContextProtocol, SQSClientProtocol
from worker.domain.errors import PermanentProvisioningError
from worker.ports.outbound.outbox_port import OutboxEvent, OutboxPort

logger = structlog.get_logger(__name__)


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


class EdiSqsConsumer(OutboxPort):
    def __init__(
        self,
        queue_name: str = "edi-tenant-sync.fifo",
        endpoint_url: str | None = None,
        region: str | None = None,
    ):
        self.queue_name = queue_name
        self.endpoint_url = endpoint_url or os.environ.get("AWS_ENDPOINT_URL")
        # Fallback for local development if missing
        if not self.endpoint_url and os.environ.get("ENVIRONMENT") == "local":
            self.endpoint_url = "http://localhost:4566"
        self.region = region or "us-east-1"
        self.session = aioboto3.Session()
        self._client: SQSClientProtocol | None = None
        self._client_context: SQSClientContextProtocol | None = None
        self._queue_url: str | None = None

    async def __aenter__(self) -> "EdiSqsConsumer":
        if not self._client:
            self._client_context = self.session.client(
                "sqs", endpoint_url=self.endpoint_url, region_name=self.region
            )
            self._client = await self._client_context.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._client_context:
            await self._client_context.__aexit__(exc_type, exc_val, exc_tb)
            self._client = None
            self._client_context = None

    async def close(self) -> None:
        """Close the adapter and release all resources."""
        if self._client_context:
            await self._client_context.__aexit__(None, None, None)
            self._client = None
            self._client_context = None

    async def _get_queue_url(self, sqs: SQSClientProtocol) -> str:
        if self._queue_url:
            return self._queue_url
        try:
            queue_url_response = await sqs.get_queue_url(QueueName=self.queue_name)
            self._queue_url = queue_url_response["QueueUrl"]
            return self._queue_url
        except Exception:
            logger.exception("sqs_queue_url_resolution_failed", queue_name=self.queue_name)
            raise

    @asynccontextmanager
    async def process_next_event(self) -> AsyncIterator[OutboxEvent | None]:
        if self._client:
            sqs = self._client
            async with self._process_with_client(sqs) as event:
                yield event
        else:
            async with (
                self.session.client(
                    "sqs", endpoint_url=self.endpoint_url, region_name=self.region
                ) as sqs,
                self._process_with_client(sqs) as event,
            ):
                yield event

    async def _parse_and_translate_body(
        self,
        sqs: SQSClientProtocol,
        queue_url: str,
        receipt_handle: str,
        message_id: str,
        body_str: str,
    ) -> dict[str, Any] | None:
        try:
            raw_body = json.loads(body_str)
            if not isinstance(raw_body, dict):
                raise TypeError("JSON body is not a mapping")

            # Handle SNS Envelope
            if "Type" in raw_body and raw_body["Type"] == "Notification" and "Message" in raw_body:
                body = json.loads(raw_body["Message"])
                if not isinstance(body, dict):
                    raise TypeError("SNS nested Message is not a mapping")
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
                            "unregistered_external_event_type",
                            external_event_type=external_event_type,
                            message_id=message_id,
                            action="leave_for_dlq",
                        )
                        return None
                    body = translated_body
                except ValueError:
                    # Permanent validation error - malformed message
                    logger.exception(
                        "permanent_validation_error",
                        external_event_type=external_event_type,
                        message_id=message_id,
                        body=body,
                        action="delete_message",
                    )
                    await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                    return None
            from typing import cast

            return cast(dict[str, Any], body)
        except json.JSONDecodeError:
            logger.exception(
                "sqs_message_json_decode_failed",
                message_id=message_id,
                payload=body_str,
            )
            await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
            return None
        except TypeError as e:
            logger.exception("sqs_message_type_error", error=str(e), message_id=message_id)
            await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
            return None

    @asynccontextmanager
    async def _process_with_client(
        self, sqs: SQSClientProtocol
    ) -> AsyncIterator[OutboxEvent | None]:
        try:
            queue_url = await self._get_queue_url(sqs)
        except Exception:  # noqa: BLE001
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

        body = await self._parse_and_translate_body(
            sqs, queue_url, receipt_handle, message_id, body_str
        )
        if body is None:
            yield None
            return

        event = SqsEvent(message_id=message_id, receipt_handle=receipt_handle, body=body)
        logger.info("sqs_event_picked_up", message_id=message_id)

        try:
            yield event
            # Delete the message on success
            await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
            logger.info("sqs_message_processed_and_deleted", message_id=message_id)
        except Exception as e:
            if isinstance(e, PermanentProvisioningError):
                logger.exception(
                    "permanent_provisioning_error", event_id=event.id, action="delete_message"
                )
                await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
            else:
                logger.exception(
                    "transient_provisioning_error", event_id=event.id, action="leave_on_queue"
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
            queue_url = await self._get_queue_url(sqs)

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
            logger.info(
                "sqs_event_published",
                event_type=event_type,
                tenant_id=tenant_id,
                queue_name=self.queue_name,
            )
