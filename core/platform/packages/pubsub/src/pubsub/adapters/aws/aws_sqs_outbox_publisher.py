"""AWS SQS Outbox Publisher implementing OutboxPublisherPort."""

from __future__ import annotations

import asyncio
import json
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Protocol, cast

import aioboto3
import structlog
from database.outbox_serializer import serialize_domain_event
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope

logger = structlog.get_logger(__name__)


class _SqsPublisherClientProtocol(Protocol):
    async def send_message(self, **kwargs: object) -> JsonDict: ...
    async def send_message_batch(self, **kwargs: object) -> JsonDict: ...


class AwsSqsOutboxPublisher(OutboxPublisherPort):
    """
    AWS SQS publisher implementing OutboxPublisherPort.
    Statically typed with zero dynamic reflection (no getattr).
    """

    def __init__(
        self,
        queue_url: str,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
        max_concurrent_batches: int = 10,
    ) -> None:
        if not queue_url:
            raise ValueError("queue_url must not be empty")
        if max_concurrent_batches <= 0:
            raise ValueError("max_concurrent_batches must be strictly positive")

        self.queue_url = queue_url
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self.max_concurrent_batches = max_concurrent_batches
        self.session = aioboto3.Session()
        self._client: _SqsPublisherClientProtocol | None = None
        self._client_context: AbstractAsyncContextManager[_SqsPublisherClientProtocol] | None = None

    @property
    def is_fifo(self) -> bool:
        return self.queue_url.endswith(".fifo")

    async def __aenter__(self) -> AwsSqsOutboxPublisher:
        if not self._client:
            self._client_context = self.session.client(
                "sqs",
                region_name=self.region_name,
                endpoint_url=self.endpoint_url,
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

    def _build_entry(
        self, event: EventEnvelope, entry_id: str, *, batch: bool
    ) -> dict[str, object]:
        attributes: dict[str, dict[str, str]] = {
            "event_type": {
                "DataType": "String",
                "StringValue": event.event_type,
            },
            "lane": {
                "DataType": "String",
                "StringValue": str(event.lane),
            },
        }
        if event.trace_id:
            attributes["trace_id"] = {
                "DataType": "String",
                "StringValue": event.trace_id,
            }

        entry: dict[str, object] = {
            "MessageBody": json.dumps(serialize_domain_event(event)),
            "MessageAttributes": attributes,
        }
        if batch:
            entry["Id"] = entry_id
        if self.is_fifo:
            entry["MessageGroupId"] = event.tenant_id or "default"
            entry["MessageDeduplicationId"] = event.idempotency_key or event.id
        return entry

    async def _send_one(self, client: _SqsPublisherClientProtocol, event: EventEnvelope) -> None:
        entry = self._build_entry(event, "0", batch=False)
        params: dict[str, object] = {
            "QueueUrl": self.queue_url,
            "MessageBody": entry["MessageBody"],
            "MessageAttributes": entry["MessageAttributes"],
        }
        if self.is_fifo:
            params["MessageGroupId"] = entry["MessageGroupId"]
            params["MessageDeduplicationId"] = entry["MessageDeduplicationId"]

        await client.send_message(**params)
        logger.info(
            "aws_sqs_event_published",
            queue_url=self.queue_url,
            event_type=event.event_type,
            event_id=event.id,
        )

    async def publish(self, event: EventEnvelope) -> None:
        try:
            if self._client:
                await self._send_one(self._client, event)
            else:
                async with self.session.client(
                    "sqs",
                    region_name=self.region_name,
                    endpoint_url=self.endpoint_url,
                ) as client:
                    await self._send_one(client, event)
        except Exception:
            logger.exception(
                "aws_sqs_publish_failed",
                queue_url=self.queue_url,
                event_id=event.id,
            )
            raise

    async def _publish_chunk(
        self, client: _SqsPublisherClientProtocol, chunk: list[EventEnvelope]
    ) -> tuple[list[str], bool, Exception | None]:
        entry_id_to_event_id = {str(index): event.id for index, event in enumerate(chunk)}
        entries = [
            self._build_entry(event, str(index), batch=True) for index, event in enumerate(chunk)
        ]

        try:
            response = await client.send_message_batch(
                QueueUrl=self.queue_url,
                Entries=entries,
            )
        except Exception as exc:
            logger.exception(
                "aws_sqs_batch_publish_chunk_failed",
                queue_url=self.queue_url,
            )
            return [], True, exc

        successful_raw = cast(list[JsonDict], response.get("Successful", []))
        chunk_successful = [entry_id_to_event_id[str(success["Id"])] for success in successful_raw]
        if chunk_successful:
            logger.info(
                "aws_sqs_batch_chunk_published",
                queue_url=self.queue_url,
                count=len(chunk_successful),
            )

        failed_raw = cast(list[JsonDict], response.get("Failed", []))
        for failed in failed_raw:
            logger.error(
                "aws_sqs_batch_publish_entry_failed",
                queue_url=self.queue_url,
                event_id=entry_id_to_event_id[str(failed["Id"])],
                code=failed.get("Code"),
                message=failed.get("Message"),
            )
        return chunk_successful, bool(failed_raw), None

    async def _publish_batch_internal(
        self, client: _SqsPublisherClientProtocol, events: list[EventEnvelope]
    ) -> list[str]:
        chunks = [events[offset : offset + 10] for offset in range(0, len(events), 10)]
        successful_ids: list[str] = []
        first_transport_error: Exception | None = None

        if self.is_fifo or len(chunks) <= 1:
            for chunk in chunks:
                chunk_success, had_failed, transport_err = await self._publish_chunk(client, chunk)
                successful_ids.extend(chunk_success)
                if transport_err is not None:
                    first_transport_error = first_transport_error or transport_err
                    if self.is_fifo:
                        break
                    continue
                if had_failed and self.is_fifo:
                    break
        else:
            semaphore = asyncio.Semaphore(self.max_concurrent_batches)

            async def _bounded_publish(
                c: list[EventEnvelope],
            ) -> tuple[list[str], bool, Exception | None]:
                async with semaphore:
                    return await self._publish_chunk(client, c)

            results = await asyncio.gather(*[_bounded_publish(c) for c in chunks])
            for chunk_success, _had_failed, transport_err in results:
                successful_ids.extend(chunk_success)
                if transport_err is not None and first_transport_error is None:
                    first_transport_error = transport_err

        if not successful_ids and first_transport_error is not None:
            raise first_transport_error
        return successful_ids

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        if not events:
            return []

        try:
            if self._client:
                return await self._publish_batch_internal(self._client, events)
            async with self.session.client(
                "sqs",
                region_name=self.region_name,
                endpoint_url=self.endpoint_url,
            ) as client:
                return await self._publish_batch_internal(client, events)
        except Exception:
            logger.exception(
                "aws_sqs_publish_batch_failed",
                queue_url=self.queue_url,
            )
            raise
