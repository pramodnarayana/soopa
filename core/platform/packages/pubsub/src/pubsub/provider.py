"""Universal Platform Composition Root for Pub/Sub publishers and consumer pumps."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Sequence

from database.provider import DatabaseProvider
from outbox.adapters.inbound.multi_shard_outbox_drain_relay import MultiShardOutboxDrainRelay
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from outbox.ports.shard_outbox_drain_port import ShardOutboxDrainPort

from pubsub.adapters.amqp.amqp_consumer_manager import AmqpConsumerManager, AmqpOutboxPublisher
from pubsub.adapters.amqp.amqp_publisher_adapter import AmqpPublisherAdapter
from pubsub.adapters.aws.aws_message_publisher_adapter import AwsMessagePublisherAdapter
from pubsub.adapters.aws.aws_sns_outbox_publisher import AwsSnsOutboxPublisher
from pubsub.adapters.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.adapters.aws.aws_sqs_consumer_manager import AwsSqsConsumerManager
from pubsub.adapters.aws.aws_sqs_outbox_publisher import AwsSqsOutboxPublisher
from pubsub.adapters.database.database_outbox_publisher import (
    DatabaseOutboxPublisher,
    DatabasePublisherAdapter,
)
from pubsub.adapters.database.direct_handler_outbox_publisher import DirectHandlerOutboxPublisher
from pubsub.adapters.database.direct_outbox_consumer_manager import DirectOutboxConsumerManager
from pubsub.adapters.database.sqlalchemy_database_queue_repository import (
    SessionScopeFactory,
    SqlAlchemyDatabaseQueueRepository,
)
from pubsub.adapters.kafka.kafka_consumer_manager import KafkaConsumerManager
from pubsub.adapters.kafka.kafka_outbox_publisher import KafkaOutboxPublisher
from pubsub.adapters.kafka.kafka_publisher_adapter import KafkaPublisherAdapter
from pubsub.adapters.memory.in_memory_consumer_manager import InMemoryConsumerManager
from pubsub.adapters.memory.in_memory_outbox_publisher import InMemoryOutboxPublisher
from pubsub.adapters.memory.in_memory_publisher_adapter import InMemoryPublisherAdapter
from pubsub.domain.dtos import TopicSubscriptionSpec
from pubsub.domain.enums import (
    BrokerType,
    PayloadDispatchMode,
    is_database_queue_uri,
    normalize_database_queue_name,
    normalize_database_topic_name,
)
from pubsub.domain.exceptions import UnsupportedBrokerSchemeError
from pubsub.ports.consumer_error_handler_port import ConsumerErrorHandlerPort
from pubsub.ports.consumer_manager_port import ConsumerManagerPort, MessageHandler
from pubsub.ports.database_queue_port import DatabaseQueuePort
from pubsub.ports.message_consumer_port import MessageConsumerPort
from pubsub.ports.message_publisher_port import MessagePublisherPort


class PubSubProvider:
    """Universal Platform Composition Root for Pub/Sub publishers and consumer pumps.

    Resolves concrete broker adapters based on URI schemes:
    - db:// or outbox:// -> Durable Single-Queue PostgreSQL Engine (FOR UPDATE SKIP LOCKED)
    - amqp:// -> RabbitMQ
    - kafka:// -> Apache Kafka (confluent-kafka librdkafka)
    - memory:// -> In-Memory Async Bus
    - sqs:// or SQS queue URL -> AWS SQS
    - sns:// or SNS topic ARN -> AWS SNS
    """

    @classmethod
    def _resolve_database_queue(
        cls,
        *,
        database_queue: DatabaseQueuePort | None = None,
        session_factory: SessionScopeFactory | None = None,
        database_url: str | None = None,
    ) -> tuple[DatabaseQueuePort, Callable[[], Awaitable[None]] | None]:
        if database_queue is not None:
            return database_queue, None
        if session_factory is not None:
            return SqlAlchemyDatabaseQueueRepository(session_factory=session_factory), None
        resolved_url = (
            database_url or os.getenv("GLOBAL_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
        ).strip()
        if not resolved_url:
            raise ValueError(
                "DATABASE_URL or GLOBAL_DATABASE_URL (or an explicit database_queue / session_factory) "
                "is required for `db://` durable PostgreSQL queues."
            )
        db_provider = DatabaseProvider.from_url(resolved_url)
        return (
            SqlAlchemyDatabaseQueueRepository(session_factory=db_provider.session),
            db_provider.close,
        )

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
        shard_drain_repo: ShardOutboxDrainPort | None = None,
        dlq_publisher: OutboxPublisherPort | None = None,
        global_outbox_repo: OutboxRepositoryPort | None = None,
        database_queue: DatabaseQueuePort | None = None,
        session_factory: SessionScopeFactory | None = None,
        database_url: str | None = None,
        subscribe_topics: Sequence[str | TopicSubscriptionSpec] | None = None,
        dispatch_mode: PayloadDispatchMode = PayloadDispatchMode.JSON_DICT,
        batch_size: int = 500,
        lock_lease_ms: int = 30000,
    ) -> ConsumerManagerPort:
        """Creates an autonomous background consumer pump for any broker or database outbox."""
        if use_in_memory or source_uri.startswith(f"{BrokerType.MEMORY.value}://"):
            return InMemoryConsumerManager(source_uri=source_uri, handler=handler)

        if (
            is_database_queue_uri(source_uri)
            or shard_drain_repo is not None
            or global_outbox_repo is not None
            or database_queue is not None
        ):
            queue_name = normalize_database_queue_name(source_uri)
            direct_publisher = DirectHandlerOutboxPublisher(
                handler=handler,
                queue_name=queue_name,
                dispatch_mode=dispatch_mode,
            )
            if shard_drain_repo is not None:
                shard_relay = MultiShardOutboxDrainRelay(
                    repository=shard_drain_repo,
                    publisher=direct_publisher,
                    dlq_publisher=dlq_publisher,
                    batch_size=batch_size,
                    lock_lease_ms=lock_lease_ms,
                    poll_interval_seconds=poll_sleep_seconds,
                )
                return DirectOutboxConsumerManager(
                    source_uri=source_uri,
                    direct_publisher=direct_publisher,
                    shard_relay=shard_relay,
                    batch_size=batch_size,
                    lock_lease_ms=lock_lease_ms,
                    poll_sleep_seconds=poll_sleep_seconds,
                )

            if global_outbox_repo is not None:
                global_processor = OutboxProcessorUseCase(
                    repository=global_outbox_repo,
                    publisher=direct_publisher,
                    max_concurrent_events=batch_size,
                    lock_lease_ms=lock_lease_ms,
                )
                return DirectOutboxConsumerManager(
                    source_uri=source_uri,
                    direct_publisher=direct_publisher,
                    global_processor=global_processor,
                    batch_size=batch_size,
                    lock_lease_ms=lock_lease_ms,
                    poll_sleep_seconds=poll_sleep_seconds,
                )

            resolved_queue, owned_db_close = cls._resolve_database_queue(
                database_queue=database_queue,
                session_factory=session_factory,
                database_url=database_url,
            )
            normalized_subs: list[TopicSubscriptionSpec] = []
            for item in subscribe_topics or ():
                if isinstance(item, TopicSubscriptionSpec):
                    normalized_subs.append(
                        TopicSubscriptionSpec(
                            topic_name=normalize_database_topic_name(item.topic_name),
                            event_types=item.event_types,
                        )
                    )
                else:
                    normalized_subs.append(
                        TopicSubscriptionSpec(topic_name=normalize_database_topic_name(item))
                    )
            return DirectOutboxConsumerManager(
                source_uri=source_uri,
                direct_publisher=direct_publisher,
                database_queue=resolved_queue,
                topic_subscriptions=normalized_subs,
                batch_size=batch_size,
                lock_lease_ms=lock_lease_ms,
                poll_sleep_seconds=poll_sleep_seconds,
                owned_db_close=owned_db_close,
            )

        if source_uri.startswith(f"{BrokerType.AMQP.value}://"):
            return AmqpConsumerManager(
                source_uri=source_uri,
                handler=handler,
                endpoint_url=endpoint_url,
            )

        if source_uri.startswith(f"{BrokerType.KAFKA.value}://"):
            servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS") or "localhost:9092"
            return KafkaConsumerManager(
                topic=source_uri,
                group_id=group_id,
                handler=handler,
                bootstrap_servers=servers,
            )

        # Default AWS SQS consumer pump
        queue_url = source_uri.removeprefix(f"{BrokerType.SQS.value}://")
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
    def create_consumer_manager_for_consumer(
        cls,
        *,
        consumer: MessageConsumerPort,
        handler: MessageHandler,
        queue_name: str,
        poll_sleep_seconds: float = 0.05,
        error_sleep_seconds: float = 1.0,
        error_handler: ConsumerErrorHandlerPort | None = None,
    ) -> ConsumerManagerPort:
        """Wraps an injected `MessageConsumerPort` behind `ConsumerManagerPort` without exposing concrete adapters."""
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
        database_queue: DatabaseQueuePort | None = None,
        session_factory: SessionScopeFactory | None = None,
        database_url: str | None = None,
    ) -> OutboxPublisherPort:
        """Creates a destination-bound OutboxPublisherPort for transactional outbox relays."""
        if use_in_memory or destination_uri.startswith(f"{BrokerType.MEMORY.value}://"):
            return InMemoryOutboxPublisher(destination_uri=destination_uri)

        if is_database_queue_uri(destination_uri):
            resolved_queue, owned_db_close = cls._resolve_database_queue(
                database_queue=database_queue,
                session_factory=session_factory,
                database_url=database_url,
            )
            return DatabaseOutboxPublisher(
                database_queue=resolved_queue,
                destination_uri=destination_uri,
                owned_db_close=owned_db_close,
            )

        if destination_uri.startswith(f"{BrokerType.AMQP.value}://"):
            return AmqpOutboxPublisher(
                destination_uri=destination_uri,
                endpoint_url=endpoint_url,
            )

        if destination_uri.startswith(f"{BrokerType.KAFKA.value}://"):
            servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS") or "localhost:9092"
            return KafkaOutboxPublisher(
                topic=destination_uri,
                bootstrap_servers=servers,
            )

        if (
            destination_uri.startswith(f"{BrokerType.SNS.value}://")
            or "arn:aws:sns" in destination_uri.lower()
        ):
            topic_arn = destination_uri.removeprefix(f"{BrokerType.SNS.value}://")
            return AwsSnsOutboxPublisher(
                topic_arn=topic_arn,
                region_name=region_name,
                endpoint_url=endpoint_url,
                max_concurrent_batches=max_concurrent_batches,
            )

        if (
            destination_uri.startswith(f"{BrokerType.SQS.value}://")
            or "queue" in destination_uri.lower()
            or "http" in destination_uri.lower()
        ):
            queue_url = destination_uri.removeprefix(f"{BrokerType.SQS.value}://")
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
        database_queue: DatabaseQueuePort | None = None,
        session_factory: SessionScopeFactory | None = None,
        database_url: str | None = None,
    ) -> MessagePublisherPort:
        """Resolves the concrete MessagePublisherPort adapter dynamically from destination URI scheme."""
        if use_in_memory or destination_uri.startswith(f"{BrokerType.MEMORY.value}://"):
            return InMemoryPublisherAdapter()

        if is_database_queue_uri(destination_uri):
            resolved_queue, owned_db_close = cls._resolve_database_queue(
                database_queue=database_queue,
                session_factory=session_factory,
                database_url=database_url,
            )
            return DatabasePublisherAdapter(
                database_queue=resolved_queue,
                owned_db_close=owned_db_close,
            )

        if destination_uri.startswith(f"{BrokerType.KAFKA.value}://"):
            servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS") or "localhost:9092"
            return KafkaPublisherAdapter(
                bootstrap_servers=servers,
                use_in_memory=use_in_memory,
            )

        if destination_uri.startswith(f"{BrokerType.AMQP.value}://"):
            return AmqpPublisherAdapter(use_in_memory=use_in_memory)

        if (
            destination_uri.startswith((f"{BrokerType.SQS.value}://", f"{BrokerType.SNS.value}://"))
            or "queue" in destination_uri.lower()
            or "arn:aws" in destination_uri.lower()
        ):
            return AwsMessagePublisherAdapter(
                region_name=region_name,
                endpoint_url=endpoint_url,
            )

        scheme = destination_uri.split("://")[0] if "://" in destination_uri else "unknown"
        raise UnsupportedBrokerSchemeError(scheme)
