"""Hexagonal port protocol for persistent streaming and pub/sub message broker transports."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from seedwork.domain.types import JsonDict

from ip.engine.domain.enums import AckVerdict
from ip.engine.domain.exceptions import ConnectionCheckError, Result
from ip.engine.domain.models.stream_definition import StreamDefinition


@dataclass(frozen=True)
class RawMessageDTO:
    """Individual raw message received from a streaming transport broker."""

    message_id: str
    raw_payload: bytes
    headers: Mapping[str, str] = field(default_factory=dict)
    partition_id: str | None = None
    broker_offset: str | None = None
    source_timestamp: datetime | None = None
    content_type: str = "application/json"


@dataclass(frozen=True)
class RawMessageBatchDTO:
    """A batch of raw streaming messages yielded by a broker consumer."""

    stream_name: str
    messages: Sequence[RawMessageDTO]
    batch_id: str | None = None


class SourceTransportPort(Protocol):
    """Base hexagonal outbound adapter port for reading data from external systems."""

    async def test_connection(
        self, config: JsonDict, credentials: JsonDict
    ) -> Result[None, ConnectionCheckError]:
        """Validates network connectivity and credentials with the upstream transport."""
        ...


class SubscribeTransportPort(SourceTransportPort, Protocol):
    """Transport port maintaining a persistent streaming subscription (Kafka, RabbitMQ, MQTT, SQS)."""

    async def start_consumer(
        self,
        stream: StreamDefinition,
        message_handler: Callable[[RawMessageBatchDTO], Awaitable[AckVerdict]],
        stop_signal: asyncio.Event,
    ) -> None:
        """Starts a persistent consumer loop, yielding batches to message_handler and ACKing strictly post-commit."""
        ...
