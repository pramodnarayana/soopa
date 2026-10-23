"""Apache Kafka streaming subscriber transport enforcing strict post-commit offset management."""

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


class KafkaConsumerClientPort(Protocol):
    """Protocol for abstract Kafka async client operations."""

    async def test_connection(self) -> Result[None, ConnectionCheckError]:
        """Validates broker bootstrap and cluster connectivity."""
        ...

    async def poll_batch(
        self, timeout_ms: int = 1000, max_records: int = 100
    ) -> Sequence[RawMessageDTO]:
        """Polls a batch of messages from subscribed Kafka topics."""
        ...

    async def commit_offsets(self, messages: Sequence[RawMessageDTO]) -> None:
        """Commits partition offsets for processed messages."""
        ...

    async def seek_to_uncommitted(self) -> None:
        """Rolls back in-memory positions to the last committed offset on NACK."""
        ...


class KafkaSubscribeTransport(SubscribeTransportPort):
    """Apache Kafka transport enforcing the Strict At-Least-Once Handshake.

    In compliance with Section 6.3:
    - Consumer Group: soopa-ip-{tenant_id}-{connection_id}
    - Offset Management: enable_auto_commit = False.
    - Offsets are committed via commit_offsets() strictly AFTER L1 database transaction commit.
    """

    def __init__(
        self,
        client: KafkaConsumerClientPort,
        batch_size: int = 100,
        poll_timeout_ms: int = 500,
    ) -> None:
        self._client = client
        self._batch_size = batch_size
        self._poll_timeout_ms = poll_timeout_ms

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
            "kafka_consumer_loop_started",
            stream=stream.stream,
            batch_size=self._batch_size,
        )
        while not stop_signal.is_set():
            try:
                messages = await self._client.poll_batch(
                    timeout_ms=self._poll_timeout_ms,
                    max_records=self._batch_size,
                )
                if not messages:
                    await asyncio.sleep(0.05)
                    continue

                batch = RawMessageBatchDTO(
                    stream_name=stream.stream,
                    messages=messages,
                )

                # Process batch through L1 atomic transaction
                verdict = await message_handler(batch)

                if verdict == AckVerdict.ACK:
                    # Offsets committed STRICTLY after L1 DB transaction commits
                    await self._client.commit_offsets(messages)
                    logger.info(
                        "kafka_offsets_committed",
                        stream=stream.stream,
                        message_count=len(messages),
                    )
                else:
                    logger.error(
                        "kafka_batch_nack_received_seeking_rollback",
                        stream=stream.stream,
                        message_count=len(messages),
                        verdict=verdict.value,
                    )
                    await self._client.seek_to_uncommitted()
                    await asyncio.sleep(0.2)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception(
                    "kafka_consumer_poll_error",
                    stream=stream.stream,
                    error=str(exc),
                )
                await asyncio.sleep(0.5)

        logger.info("kafka_consumer_loop_stopped", stream=stream.stream)
