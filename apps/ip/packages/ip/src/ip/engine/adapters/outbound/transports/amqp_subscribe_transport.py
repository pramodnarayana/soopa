"""RabbitMQ / AMQP 0-9-1 streaming subscriber transport enforcing strict post-commit ACKs and DLX routing."""

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


class AmqpMessageHandlePort(Protocol):
    """Handle to a broker message for atomic ACK / NACK / Reject."""

    @property
    def message(self) -> RawMessageDTO: ...

    async def ack(self) -> None:
        """Acknowledges the message after successful L1 commit."""
        ...

    async def nack(self, requeue: bool = True) -> None:
        """Negatively acknowledges the message for broker redelivery."""
        ...

    async def reject(self, requeue: bool = False) -> None:
        """Rejects the poison message to route directly to Dead Letter Exchange (soopa.dlx)."""
        ...


class AmqpConsumerClientPort(Protocol):
    """Protocol for abstract AMQP channel operations."""

    async def test_connection(self) -> Result[None, ConnectionCheckError]:
        """Validates broker connectivity and exchange/queue declaration."""
        ...

    async def fetch_batch(
        self, queue_name: str, batch_size: int, timeout_ms: int = 500
    ) -> Sequence[AmqpMessageHandlePort]:
        """Fetches up to batch_size pre-fetched messages from the AMQP queue."""
        ...


class AmqpSubscribeTransport(SubscribeTransportPort):
    """RabbitMQ / AMQP 0-9-1 subscriber transport enforcing strict post-commit acknowledgment.

    In compliance with Section 6.3:
    - Library/Semantics: aio-pika / AMQP 0-9-1.
    - Channel Prefetch (basic_qos): Configurable prefetch count (default 50).
    - Acknowledgment: message.ack() sent STRICTLY after L1 commit.
    - Poison Pill Handling: Unparsable / terminal failures routed to Dead Letter Exchange (soopa.dlx).
    """

    def __init__(
        self,
        client: AmqpConsumerClientPort,
        queue_name: str,
        prefetch_count: int = 50,
        dlx_exchange: str = "soopa.dlx",
    ) -> None:
        self._client = client
        self._queue_name = queue_name
        self._prefetch_count = prefetch_count
        self._dlx_exchange = dlx_exchange

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
            "amqp_consumer_loop_started",
            queue=self._queue_name,
            prefetch=self._prefetch_count,
            stream=stream.stream,
        )
        while not stop_signal.is_set():
            try:
                handles = await self._client.fetch_batch(
                    queue_name=self._queue_name,
                    batch_size=self._prefetch_count,
                    timeout_ms=500,
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

                # Handshake: ACK / NACK / REJECT strictly after L1 commit outcome
                if verdict == AckVerdict.ACK:
                    for h in handles:
                        await h.ack()
                    logger.info(
                        "amqp_messages_acked",
                        queue=self._queue_name,
                        count=len(handles),
                    )
                elif verdict == AckVerdict.REJECT:
                    for h in handles:
                        await h.reject(requeue=False)
                    logger.error(
                        "amqp_messages_rejected_to_dlx",
                        queue=self._queue_name,
                        count=len(handles),
                        dlx=self._dlx_exchange,
                    )
                else:
                    for h in handles:
                        await h.nack(requeue=True)
                    logger.error(
                        "amqp_messages_nacked_for_requeue",
                        queue=self._queue_name,
                        count=len(handles),
                    )
                    await asyncio.sleep(0.2)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception(
                    "amqp_consumer_loop_error",
                    queue=self._queue_name,
                    error=str(exc),
                )
                await asyncio.sleep(0.5)

        logger.info("amqp_consumer_loop_stopped", queue=self._queue_name)
