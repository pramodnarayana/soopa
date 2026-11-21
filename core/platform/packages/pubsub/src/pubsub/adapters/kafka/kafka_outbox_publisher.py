"""Apache Kafka Outbox Publisher implementing OutboxPublisherPort."""

from __future__ import annotations

import asyncio
import json

import structlog
from confluent_kafka import Producer
from database.outbox_serializer import serialize_domain_event
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.events import EventEnvelope

logger = structlog.get_logger(__name__)


class KafkaOutboxPublisher(OutboxPublisherPort):
    """
    Apache Kafka publisher implementing OutboxPublisherPort for transactional outbox relays.
    """

    def __init__(
        self,
        topic: str,
        bootstrap_servers: str = "localhost:9092",
        producer: Producer | None = None,
    ) -> None:
        self.topic = topic.removeprefix("kafka://")
        self.bootstrap_servers = bootstrap_servers
        self._producer = producer

    def _get_producer(self) -> Producer:
        if self._producer is None:
            self._producer = Producer({"bootstrap.servers": self.bootstrap_servers})
        return self._producer

    async def publish(self, event: EventEnvelope) -> None:
        producer = self._get_producer()
        payload = json.dumps(serialize_domain_event(event)).encode("utf-8")
        key = (event.tenant_id or event.id).encode("utf-8")

        delivery_future: asyncio.Future[None] = asyncio.get_running_loop().create_future()

        def _on_delivery(err: object, msg: object) -> None:
            if err:
                delivery_future.set_exception(RuntimeError(f"Kafka delivery failed: {err}"))
            else:
                delivery_future.set_result(None)

        producer.produce(
            topic=self.topic,
            value=payload,
            key=key,
            on_delivery=_on_delivery,
        )
        producer.poll(0)
        await delivery_future
        logger.info("kafka_outbox_event_published", topic=self.topic, event_id=event.id)

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        if not events:
            return []

        producer = self._get_producer()
        successful_ids: list[str] = []
        futures: list[tuple[str, asyncio.Future[None]]] = []
        loop = asyncio.get_running_loop()

        for event in events:
            fut: asyncio.Future[None] = loop.create_future()
            event_id = event.id
            payload = json.dumps(serialize_domain_event(event)).encode("utf-8")
            key = (event.tenant_id or event.id).encode("utf-8")

            def _delivery_cb(
                err: object, msg: object, target_fut: asyncio.Future[None] = fut
            ) -> None:
                if err:
                    target_fut.set_exception(RuntimeError(f"Kafka delivery error: {err}"))
                else:
                    target_fut.set_result(None)

            producer.produce(
                topic=self.topic,
                value=payload,
                key=key,
                on_delivery=_delivery_cb,
            )
            futures.append((event_id, fut))

        producer.flush()

        for eid, fut in futures:
            try:
                await fut
                successful_ids.append(eid)
            except Exception as exc:  # noqa: BLE001 - Batch iteration isolates per-message failures to track successful IDs
                logger.error(
                    "kafka_outbox_batch_entry_failed",
                    topic=self.topic,
                    event_id=eid,
                    error=str(exc),
                )

        return successful_ids
