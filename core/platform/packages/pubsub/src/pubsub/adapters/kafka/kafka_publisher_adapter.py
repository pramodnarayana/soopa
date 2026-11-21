"""Enterprise Apache Kafka Publisher Adapter backed by confluent-kafka (librdkafka)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence

import structlog
from confluent_kafka import KafkaError, Message, Producer
from seedwork.domain.exceptions import Result
from seedwork.events import EventEnvelope

from pubsub.domain.dtos import PublishResultDTO
from pubsub.domain.exceptions import PublisherError
from pubsub.ports.message_publisher_port import MessagePublisherPort

logger = structlog.get_logger(__name__)


class KafkaPublisherAdapter(MessagePublisherPort):
    """Production-grade Apache Kafka publisher backed by native C librdkafka.

    Features:
    - High-throughput asynchronous publishing with zero event-loop GIL starvation.
    - Configurable Snappy, Zstandard, LZ4, or Gzip compression.
    - Configurable batching and queue buffering (linger.ms / queue.buffering.max.ms).
    - Idempotent producer guarantees (enable.idempotence=true, acks=all).
    """

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        client_id: str = "pubsub-kafka-producer",
        acks: str = "all",
        linger_ms: int = 20,
        compression_type: str = "snappy",
        producer: Producer | None = None,
        use_in_memory: bool = False,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._client_id = client_id
        self._acks = acks
        self._linger_ms = linger_ms
        self._compression_type = compression_type
        self._producer = producer
        self._use_in_memory = use_in_memory
        self._in_memory_records: list[
            tuple[str, bytes, bytes | None, Mapping[str, str] | None]
        ] = []

    @property
    def in_memory_records(self) -> list[tuple[str, bytes, bytes | None, Mapping[str, str] | None]]:
        return self._in_memory_records

    def _extract_topic(self, uri: str) -> str:
        if uri.startswith("kafka://"):
            return uri.removeprefix("kafka://")
        return uri

    def _get_producer(self) -> Producer:
        if self._producer is None:
            conf: dict[str, str | int | bool] = {
                "bootstrap.servers": self._bootstrap_servers,
                "client.id": self._client_id,
                "acks": self._acks,
                "compression.type": self._compression_type,
                "queue.buffering.max.ms": self._linger_ms,
                "enable.idempotence": self._acks.lower() in ("all", "-1"),
                "retries": 5,
                "retry.backoff.ms": 250,
            }
            self._producer = Producer(conf)
        return self._producer

    async def publish(
        self,
        destination_uri: str,
        message: bytes | EventEnvelope,
        key: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Result[PublishResultDTO, Exception]:
        topic = self._extract_topic(destination_uri)

        if isinstance(message, EventEnvelope):
            raw_body = json.dumps(message.to_dict()).encode("utf-8")
            event_key = message.idempotency_key.encode("utf-8") if message.idempotency_key else None
            effective_key = key or event_key
            merged_headers = dict(headers or {})
            merged_headers["event_type"] = message.event_type
            merged_headers["event_id"] = message.id
        else:
            raw_body = message
            effective_key = key
            merged_headers = dict(headers or {})

        headers_list: list[tuple[str, str | bytes | None]] | None = (
            [(str(k), v.encode("utf-8")) for k, v in merged_headers.items()]
            if merged_headers
            else None
        )

        if self._use_in_memory:
            self._in_memory_records.append((topic, raw_body, effective_key, merged_headers))
            result = PublishResultDTO(
                destination_uri=destination_uri,
                message_id=f"{topic}:0:{len(self._in_memory_records) - 1}",
                partition=0,
                offset=len(self._in_memory_records) - 1,
            )
            return Result.ok(result)

        producer = self._get_producer()
        loop = asyncio.get_running_loop()
        delivery_future: asyncio.Future[Result[PublishResultDTO, Exception]] = loop.create_future()

        def _on_delivery(err: KafkaError | None, msg: Message) -> None:
            if err is not None:
                err_msg = err.str()
                logger.error("kafka_delivery_failed", topic=topic, error=err_msg)
                loop.call_soon_threadsafe(
                    delivery_future.set_result,
                    Result.fail(PublisherError(f"Kafka delivery failed for {topic}: {err_msg}")),
                )
            else:
                res = PublishResultDTO(
                    destination_uri=destination_uri,
                    message_id=f"{msg.topic()}:{msg.partition()}:{msg.offset()}",
                    partition=msg.partition(),
                    offset=msg.offset(),
                )
                loop.call_soon_threadsafe(delivery_future.set_result, Result.ok(res))

        try:
            producer.produce(
                topic=topic,
                value=raw_body,
                key=effective_key,
                headers=headers_list,
                on_delivery=_on_delivery,
            )
            # Service delivery callbacks
            producer.poll(0)
            return await delivery_future
        except BufferError:
            logger.warning("kafka_producer_queue_full_flushing", topic=topic)
            producer.flush(1.0)
            producer.produce(
                topic=topic,
                value=raw_body,
                key=effective_key,
                headers=headers_list,
                on_delivery=_on_delivery,
            )
            producer.poll(0)
            return await delivery_future
        except Exception as exc:  # noqa: BLE001 - Result pattern boundary captures transport exceptions into Result.fail
            logger.error("kafka_produce_exception", topic=topic, error=str(exc))
            return Result.fail(PublisherError(f"Failed to produce message to {topic}: {exc}"))

    async def publish_batch(
        self,
        destination_uri: str,
        messages: Sequence[bytes | EventEnvelope],
        keys: Sequence[bytes | None] | None = None,
        headers: Sequence[Mapping[str, str] | None] | None = None,
    ) -> Result[tuple[PublishResultDTO, ...], Exception]:
        results: list[PublishResultDTO] = []
        for idx, msg in enumerate(messages):
            k = keys[idx] if keys and idx < len(keys) else None
            h = headers[idx] if headers and idx < len(headers) else None
            res = await self.publish(destination_uri, msg, key=k, headers=h)
            if res.is_err:
                err = res.error if res.error is not None else Exception("Unknown error")
                return Result.fail(err)
            results.append(res.unwrap())
        return Result.ok(tuple(results))

    async def flush(self, timeout_seconds: float = 5.0) -> None:
        if self._producer is not None:
            await asyncio.to_thread(self._producer.flush, timeout_seconds)
