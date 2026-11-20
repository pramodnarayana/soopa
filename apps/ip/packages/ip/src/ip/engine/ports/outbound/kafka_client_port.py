"""Hexagonal outbound port protocols and DTOs for Apache Kafka client operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from seedwork.domain.types import JsonDict

from ip.engine.domain.exceptions import ConnectionCheckError, KafkaConnectionError, Result


@dataclass(frozen=True)
class KafkaProduceResultDTO:
    """Outcome of writing a record to an Apache Kafka topic."""

    topic: str
    partition: int
    offset: int
    timestamp_ms: int


class KafkaProducerClientPort(Protocol):
    """Protocol for abstract Kafka async producer client operations."""

    async def test_connection(self) -> Result[None, ConnectionCheckError]:
        """Validates broker bootstrap and cluster connectivity."""
        ...

    async def list_topics(self) -> Result[Sequence[str], KafkaConnectionError]:
        """Returns list of accessible topic names on the Kafka cluster."""
        ...

    async def produce(
        self,
        topic: str,
        value: bytes,
        key: bytes | None = None,
        headers: Mapping[str, bytes] | None = None,
        partition: int | None = None,
    ) -> Result[KafkaProduceResultDTO, KafkaConnectionError]:
        """Publishes a single message to a Kafka topic and returns partition/offset."""
        ...


class KafkaProducerClientFactoryPort(Protocol):
    """Factory protocol for producing KafkaProducerClientPort instances from connection configuration."""

    def create_producer(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> KafkaProducerClientPort:
        """Creates or resolves a producer client configured with the given credentials and settings."""
        ...


__all__ = [
    "KafkaProduceResultDTO",
    "KafkaProducerClientFactoryPort",
    "KafkaProducerClientPort",
]
