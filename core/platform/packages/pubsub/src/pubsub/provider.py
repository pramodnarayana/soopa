"""Universal Platform Composition Root for Pub/Sub publishers and consumer pumps."""

from __future__ import annotations

import os

from outbox.ports.outbox_publisher_port import OutboxPublisherPort

from pubsub.adapters.amqp.amqp_publisher_adapter import AmqpPublisherAdapter
from pubsub.adapters.aws.aws_message_publisher_adapter import AwsMessagePublisherAdapter
from pubsub.adapters.aws.aws_sns_outbox_publisher import AwsSnsOutboxPublisher
from pubsub.adapters.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.adapters.aws.aws_sqs_consumer_manager import AwsSqsConsumerManager
from pubsub.adapters.aws.aws_sqs_outbox_publisher import AwsSqsOutboxPublisher
from pubsub.adapters.kafka.kafka_consumer_manager import KafkaConsumerManager
from pubsub.adapters.kafka.kafka_outbox_publisher import KafkaOutboxPublisher
from pubsub.adapters.kafka.kafka_publisher_adapter import KafkaPublisherAdapter
from pubsub.adapters.memory.in_memory_consumer_manager import InMemoryConsumerManager
from pubsub.adapters.memory.in_memory_outbox_publisher import InMemoryOutboxPublisher
from pubsub.adapters.memory.in_memory_publisher_adapter import InMemoryPublisherAdapter
from pubsub.domain.exceptions import UnsupportedBrokerSchemeError
from pubsub.ports.consumer_error_handler_port import ConsumerErrorHandlerPort
from pubsub.ports.consumer_manager_port import ConsumerManagerPort, MessageHandler
from pubsub.ports.message_publisher_port import MessagePublisherPort


class PubSubProvider:
    """Universal Platform Provider for Pub/Sub publishers and consumer pumps.

    Resolves concrete broker adapters based on URI schemes:
    - sqs:// or SQS queue URL -> AWS SQS
    - sns:// or SNS topic ARN -> AWS SNS
    - kafka:// -> Apache Kafka (confluent-kafka librdkafka)
    - amqp:// -> RabbitMQ
    - memory:// -> In-Memory Async Bus
    """

    @classmethod
    def create_consumer_manager(
        cls,
        source_uri: str,
        handler: MessageHandler,
        *,
        group_id: str = "soopa-consumer",
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
        bootstrap_servers: str | None = None,
        use_in_memory: bool = False,
        error_handler: ConsumerErrorHandlerPort | None = None,
        poll_sleep_seconds: float = 0.1,
        error_sleep_seconds: float = 5.0,
    ) -> ConsumerManagerPort:
        """Creates an autonomous background consumer pump for any broker."""
        if use_in_memory or source_uri.startswith("memory://"):
            return InMemoryConsumerManager(source_uri=source_uri, handler=handler)

        if source_uri.startswith("kafka://"):
            servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS") or "localhost:9092"
            return KafkaConsumerManager(
                topic=source_uri,
                group_id=group_id,
                handler=handler,
                bootstrap_servers=servers,
            )

        # Default AWS SQS consumer pump
        queue_url = source_uri.removeprefix("sqs://")
        consumer = AwsSqsConsumer(
            queue_url=queue_url,
            region_name=region_name,
            endpoint_url=endpoint_url,
        )
        queue_name = queue_url.rsplit("/", 1)[-1]
        return AwsSqsConsumerManager(
            consumer=consumer,
            handler=handler,
            queue_name=queue_name,
            poll_sleep_seconds=poll_sleep_seconds,
            error_sleep_seconds=error_sleep_seconds,
            error_handler=error_handler,
        )

    @classmethod
    def create_outbox_publisher(
        cls,
        destination_uri: str,
        *,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
        bootstrap_servers: str | None = None,
        use_in_memory: bool = False,
        max_concurrent_batches: int = 10,
    ) -> OutboxPublisherPort:
        """Creates a destination-bound OutboxPublisherPort for transactional outbox relays."""
        if use_in_memory or destination_uri.startswith("memory://"):
            return InMemoryOutboxPublisher(destination_uri=destination_uri)

        if destination_uri.startswith("kafka://"):
            servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS") or "localhost:9092"
            return KafkaOutboxPublisher(
                topic=destination_uri,
                bootstrap_servers=servers,
            )

        if destination_uri.startswith("sns://") or "arn:aws:sns" in destination_uri.lower():
            topic_arn = destination_uri.removeprefix("sns://")
            return AwsSnsOutboxPublisher(
                topic_arn=topic_arn,
                region_name=region_name,
                endpoint_url=endpoint_url,
                max_concurrent_batches=max_concurrent_batches,
            )

        if (
            destination_uri.startswith("sqs://")
            or "queue" in destination_uri.lower()
            or "http" in destination_uri.lower()
        ):
            queue_url = destination_uri.removeprefix("sqs://")
            return AwsSqsOutboxPublisher(
                queue_url=queue_url,
                region_name=region_name,
                endpoint_url=endpoint_url,
                max_concurrent_batches=max_concurrent_batches,
            )

        scheme = destination_uri.split("://")[0] if "://" in destination_uri else "unknown"
        raise UnsupportedBrokerSchemeError(scheme)

    @classmethod
    def create_publisher(
        cls,
        destination_uri: str,
        *,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
        bootstrap_servers: str | None = None,
        use_in_memory: bool = False,
    ) -> MessagePublisherPort:
        """Resolves the concrete MessagePublisherPort adapter dynamically from destination URI scheme."""
        if use_in_memory or destination_uri.startswith("memory://"):
            return InMemoryPublisherAdapter()

        if destination_uri.startswith("kafka://"):
            servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS") or "localhost:9092"
            return KafkaPublisherAdapter(
                bootstrap_servers=servers,
                use_in_memory=use_in_memory,
            )

        if destination_uri.startswith("amqp://"):
            return AmqpPublisherAdapter(use_in_memory=use_in_memory)

        if (
            destination_uri.startswith(("sqs://", "sns://"))
            or "queue" in destination_uri.lower()
            or "arn:aws" in destination_uri.lower()
        ):
            return AwsMessagePublisherAdapter(
                region_name=region_name,
                endpoint_url=endpoint_url,
            )

        scheme = destination_uri.split("://")[0] if "://" in destination_uri else "unknown"
        raise UnsupportedBrokerSchemeError(scheme)
