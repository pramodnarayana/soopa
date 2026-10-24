"""Cloud queue subscriber transport (AWS SQS, Azure Service Bus, GCP Pub/Sub)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

import structlog
from ip.engine.domain.enums import AckVerdict
from ip.engine.domain.exceptions import ConnectionCheckError, Result
from ip.engine.domain.models.stream_definition import StreamDefinition
from ip.engine.ports.outbound.subscribe_transport_port import (
    RawMessageBatchDTO,
    RawMessageDTO,
    SubscribeTransportPort,
)
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


class CloudQueueMessageHandlePort(Protocol):
    """Handle to a cloud queue message holding receipt handles for post-commit deletion."""

    @property
    def message(self) -> RawMessageDTO: ...

    @property
    def receipt_handle(self) -> str: ...


class CloudQueueConsumerClientPort(Protocol):
    """Protocol for abstract cloud queue client operations."""

    async def test_connection(self) -> Result[None, ConnectionCheckError]:
        """Validates queue URL/ARN resolution and cloud IAM permissions."""
        ...

    async def receive_messages(
        self,
        queue_url: str,
        max_messages: int = 10,
        wait_time_seconds: int = 20,
    ) -> Sequence[CloudQueueMessageHandlePort]:
        """Long-polls messages from the cloud queue."""
        ...

    async def delete_batch(self, queue_url: str, receipt_handles: Sequence[str]) -> None:
        """Deletes messages in batch after successful L1 commit."""
        ...


class CloudQueueSubscribeTransport(SubscribeTransportPort):
    """Cloud queue subscriber transport (AWS SQS, Azure Service Bus, GCP Pub/Sub).

    In compliance with Section 6.3:
    - Long-polling: WaitTimeSeconds = 20, MaxNumberOfMessages = 10.
    - Post-Commit Deletion: delete_batch() called strictly AFTER L1 database transaction commits.
    - Redelivery on NACK: On L1 failure, messages are NOT deleted, so visibility timeout expires
      and cloud queue safely redelivers.
    """

    def __init__(
        self,
        client: CloudQueueConsumerClientPort,
        queue_url: str,
        max_messages: int = 10,
        wait_time_seconds: int = 20,
    ) -> None:
        self._client = client
        self._queue_url = queue_url
        self._max_messages = max_messages
        self._wait_time_seconds = wait_time_seconds

    async def test_connection(
        self, config: JsonDict, credentials: JsonDict
    ) -> Result[None, ConnectionCheckError]:
        return await self._client.test_connection()

    async def start_consumer(
        self,
        stream: StreamDefinition,
        message_handler: Callable[[RawMessageBatchDTO], Awaitable[AckVerdict]],
        stop_signal: asyncio.Event,
    ) -> None:
        logger.info(
            "cloud_queue_consumer_loop_started",
            queue_url=self._queue_url,
            max_messages=self._max_messages,
            wait_time_seconds=self._wait_time_seconds,
            stream=stream.stream,
        )
        while not stop_signal.is_set():
            try:
                handles = await self._client.receive_messages(
                    queue_url=self._queue_url,
                    max_messages=self._max_messages,
                    wait_time_seconds=self._wait_time_seconds,
                )
                if not handles:
                    await asyncio.sleep(0.05)
                    continue

                raw_messages = [h.message for h in handles]
                batch = RawMessageBatchDTO(
                    stream_name=stream.stream,
                    messages=raw_messages,
                )

                # Process batch through atomic L1 transaction
                verdict = await message_handler(batch)

                # Post-Commit Deletion
                if verdict == AckVerdict.ACK:
                    receipts = [h.receipt_handle for h in handles]
                    await self._client.delete_batch(self._queue_url, receipts)
                    logger.info(
                        "cloud_queue_messages_deleted_post_commit",
                        queue_url=self._queue_url,
                        count=len(receipts),
                    )
                else:
                    logger.error(
                        "cloud_queue_messages_withheld_for_visibility_expiry",
                        queue_url=self._queue_url,
                        count=len(handles),
                    )
                    await asyncio.sleep(0.2)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception(
                    "cloud_queue_consumer_loop_error",
                    queue_url=self._queue_url,
                    error=str(exc),
                )
                await asyncio.sleep(0.5)

        logger.info("cloud_queue_consumer_loop_stopped", queue_url=self._queue_url)
