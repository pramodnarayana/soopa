"""RabbitMQ / AMQP Consumer Manager and Outbox Publisher port adapters."""

from __future__ import annotations

import asyncio

from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.events import EventEnvelope

from pubsub.ports.consumer_manager_port import ConsumerManagerPort, MessageHandler


class AmqpOutboxPublisher(OutboxPublisherPort):
    """OutboxPublisherPort placeholder for RabbitMQ (`amqp://`) destinations.

    Requires an explicit AMQP broker transport client; never falls back to ephemeral RAM queues.
    """

    def __init__(self, destination_uri: str, endpoint_url: str | None = None) -> None:
        self.destination_uri = destination_uri
        self.endpoint_url = endpoint_url

    async def publish(self, event: EventEnvelope) -> None:
        raise NotImplementedError(
            "AmqpOutboxPublisher requires a configured AMQP broker driver (e.g., aio-pika). "
            "Use `db://` for durable zero-broker PostgreSQL queueing or `kafka://` for streaming."
        )

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        raise NotImplementedError(
            "AmqpOutboxPublisher requires a configured AMQP broker driver (e.g., aio-pika). "
            "Use `db://` for durable zero-broker PostgreSQL queueing or `kafka://` for streaming."
        )


class AmqpConsumerManager(ConsumerManagerPort):
    """ConsumerManagerPort placeholder for RabbitMQ (`amqp://`) sources.

    Requires an explicit AMQP broker transport client; never falls back to ephemeral RAM queues.
    """

    def __init__(
        self,
        source_uri: str,
        handler: MessageHandler,
        *,
        endpoint_url: str | None = None,
    ) -> None:
        self.source_uri = source_uri
        self.handler = handler
        self.endpoint_url = endpoint_url

    def start(self) -> None:
        raise NotImplementedError(
            "AmqpConsumerManager requires a configured AMQP broker driver (e.g., aio-pika). "
            "Use `db://` for durable zero-broker PostgreSQL queueing or `kafka://` for streaming."
        )

    async def stop(self) -> None:
        return None

    async def health_check(self) -> bool:
        return False

    @property
    def task(self) -> asyncio.Task[None] | None:
        return None

    def background_tasks(self) -> list[asyncio.Task[object]]:
        return []
