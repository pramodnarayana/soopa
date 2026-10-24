"""MQTT streaming subscriber transport with QoS 1/2 acknowledgements and topic subscriptions."""

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


class MqttMessageHandlePort(Protocol):
    """Handle to an in-flight MQTT QoS 1/2 message for delayed PUBACK / PUBREC."""

    @property
    def message(self) -> RawMessageDTO: ...

    async def acknowledge_publish(self) -> None:
        """Sends PUBACK (QoS 1) or PUBREC (QoS 2) back to the broker after L1 DB commit."""
        ...


class MqttConsumerClientPort(Protocol):
    """Protocol for abstract MQTT client subscriptions."""

    async def test_connection(self) -> Result[None, ConnectionCheckError]:
        """Validates MQTT broker connectivity and TLS/credentials handshake."""
        ...

    async def subscribe(self, topic: str, qos: int = 1) -> None:
        """Subscribes to hierarchical topic filter (e.g. sensors/+/telemetry)."""
        ...

    async def fetch_messages(
        self, max_messages: int = 50, timeout_ms: int = 500
    ) -> Sequence[MqttMessageHandlePort]:
        """Polls received MQTT messages from the client message buffer."""
        ...

    async def reconnect(self) -> None:
        """Disconnects and reconnects with persistent session to trigger broker redelivery."""
        ...


class MqttSubscribeTransport(SubscribeTransportPort):
    """MQTT subscriber transport for Smart Grid AMI interval readings and IoT streams.

    In compliance with Section 6.3:
    - Library/Semantics: aiomqtt / MQTT 3.1.1 & 5.0.
    - QoS: QoS 1 (At least once) or QoS 2 (Exactly once).
    - Wildcard Subscriptions: Hierarchical topics.
    - Acknowledgment: PUBACK / PUBREC dispatched only after L1 database commit.
    """

    def __init__(
        self,
        client: MqttConsumerClientPort,
        topic_filter: str,
        qos: int = 1,
        batch_size: int = 50,
    ) -> None:
        self._client = client
        self._topic_filter = topic_filter
        self._qos = qos
        self._batch_size = batch_size

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
            "mqtt_consumer_loop_started",
            topic_filter=self._topic_filter,
            qos=self._qos,
            stream=stream.stream,
        )
        await self._client.subscribe(self._topic_filter, qos=self._qos)

        while not stop_signal.is_set():
            try:
                handles = await self._client.fetch_messages(
                    max_messages=self._batch_size,
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

                # Send PUBACK / PUBREC strictly after L1 commit
                if verdict == AckVerdict.ACK:
                    for h in handles:
                        await h.acknowledge_publish()
                    logger.info(
                        "mqtt_puback_dispatched",
                        topic_filter=self._topic_filter,
                        count=len(handles),
                    )
                elif verdict == AckVerdict.REJECT:
                    # Batch was durably rejected; acknowledge publish so broker does not redeliver forever
                    for h in handles:
                        await h.acknowledge_publish()
                    logger.error(
                        "mqtt_batch_rejected_terminal",
                        topic_filter=self._topic_filter,
                        count=len(handles),
                        verdict=verdict.value,
                    )
                else:
                    logger.error(
                        "mqtt_batch_nack_triggering_redelivery",
                        topic_filter=self._topic_filter,
                        count=len(handles),
                    )
                    try:
                        await self._client.reconnect()
                    except Exception as rec_exc:
                        logger.exception(
                            "mqtt_client_reconnect_failed",
                            topic_filter=self._topic_filter,
                            error=str(rec_exc),
                        )
                    await asyncio.sleep(0.2)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception(
                    "mqtt_consumer_loop_error",
                    topic_filter=self._topic_filter,
                    error=str(exc),
                )
                await asyncio.sleep(0.5)

        logger.info("mqtt_consumer_loop_stopped", topic_filter=self._topic_filter)
