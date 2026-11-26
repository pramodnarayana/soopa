"""Universal Platform Composition Root for Pub/Sub publishers and consumer pumps."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Sequence
from functools import lru_cache

import structlog
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
    AMQP_QUEUE_SCHEMES,
    DATABASE_QUEUE_SCHEMES,
    BrokerType,
    PayloadDispatchMode,
    normalize_database_queue_name,
    normalize_database_topic_name,
)
from pubsub.domain.exceptions import UnsupportedBrokerSchemeError
from pubsub.ports.consumer_error_handler_port import ConsumerErrorHandlerPort
from pubsub.ports.consumer_manager_port import ConsumerManagerPort, MessageHandler
from pubsub.ports.database_queue_port import DatabaseQueuePort
from pubsub.ports.message_consumer_port import MessageConsumerPort
from pubsub.ports.message_publisher_port import MessagePublisherPort
from pubsub.registry import (
    BrokerPolicyGroup,
    BrokerTransportRegistry,
    BrokerTransportSpec,
    ConsumerBuildRequest,
    OutboxPublisherBuildRequest,
    PublisherBuildRequest,
    extract_uri_scheme_label,
)

logger = structlog.get_logger(__name__)

_AWS_ENDPOINT_FAMILY = "aws"
_AWS_POLICY_GROUP = _AWS_ENDPOINT_FAMILY


def _resolve_database_queue(
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


def _build_database_consumer(req: ConsumerBuildRequest) -> ConsumerManagerPort:
    queue_name = normalize_database_queue_name(req.source_uri)
    direct_publisher = DirectHandlerOutboxPublisher(
        handler=req.handler,
        queue_name=queue_name,
        dispatch_mode=req.dispatch_mode,
    )
    if req.shard_drain_repo is not None:
        shard_relay = MultiShardOutboxDrainRelay(
            repository=req.shard_drain_repo,
            publisher=direct_publisher,
            dlq_publisher=req.dlq_publisher,
            batch_size=req.batch_size,
            lock_lease_ms=req.lock_lease_ms,
            poll_interval_seconds=req.poll_sleep_seconds,
        )
        return DirectOutboxConsumerManager(
            source_uri=req.source_uri,
            direct_publisher=direct_publisher,
            shard_relay=shard_relay,
            batch_size=req.batch_size,
            lock_lease_ms=req.lock_lease_ms,
            poll_sleep_seconds=req.poll_sleep_seconds,
        )

    if req.global_outbox_repo is not None:
        global_processor = OutboxProcessorUseCase(
            repository=req.global_outbox_repo,
            publisher=direct_publisher,
            max_concurrent_events=req.batch_size,
            lock_lease_ms=req.lock_lease_ms,
        )
        return DirectOutboxConsumerManager(
            source_uri=req.source_uri,
            direct_publisher=direct_publisher,
            global_processor=global_processor,
            batch_size=req.batch_size,
            lock_lease_ms=req.lock_lease_ms,
            poll_sleep_seconds=req.poll_sleep_seconds,
        )

    resolved_queue, owned_db_close = _resolve_database_queue(
        database_queue=req.database_queue,
        session_factory=req.session_factory,
        database_url=req.database_url,
    )
    normalized_subs = [
        TopicSubscriptionSpec(
            topic_name=normalize_database_topic_name(item.topic_name),
            event_types=item.event_types,
        )
        if isinstance(item, TopicSubscriptionSpec)
        else TopicSubscriptionSpec(topic_name=normalize_database_topic_name(item))
        for item in (req.subscribe_topics or ())
    ]
    return DirectOutboxConsumerManager(
        source_uri=req.source_uri,
        direct_publisher=direct_publisher,
        database_queue=resolved_queue,
        topic_subscriptions=normalized_subs,
        batch_size=req.batch_size,
        lock_lease_ms=req.lock_lease_ms,
        poll_sleep_seconds=req.poll_sleep_seconds,
        owned_db_close=owned_db_close,
    )


def _build_database_outbox_publisher(req: OutboxPublisherBuildRequest) -> OutboxPublisherPort:
    resolved_queue, owned_db_close = _resolve_database_queue(
        database_queue=req.database_queue,
        session_factory=req.session_factory,
        database_url=req.database_url,
    )
    return DatabaseOutboxPublisher(
        database_queue=resolved_queue,
        destination_uri=req.destination_uri,
        owned_db_close=owned_db_close,
    )


def _build_database_publisher(req: PublisherBuildRequest) -> MessagePublisherPort:
    resolved_queue, owned_db_close = _resolve_database_queue(
        database_queue=req.database_queue,
        session_factory=req.session_factory,
        database_url=req.database_url,
    )
    return DatabasePublisherAdapter(
        database_queue=resolved_queue,
        owned_db_close=owned_db_close,
    )


def _build_memory_consumer(req: ConsumerBuildRequest) -> ConsumerManagerPort:
    return InMemoryConsumerManager(source_uri=req.source_uri, handler=req.handler)


def _build_memory_outbox_publisher(req: OutboxPublisherBuildRequest) -> OutboxPublisherPort:
    return InMemoryOutboxPublisher(destination_uri=req.destination_uri)


def _build_memory_publisher(_req: PublisherBuildRequest) -> MessagePublisherPort:
    return InMemoryPublisherAdapter()


def _build_amqp_consumer(req: ConsumerBuildRequest) -> ConsumerManagerPort:
    return AmqpConsumerManager(
        source_uri=req.source_uri,
        handler=req.handler,
        endpoint_url=req.endpoint_url,
    )


def _build_amqp_outbox_publisher(req: OutboxPublisherBuildRequest) -> OutboxPublisherPort:
    return AmqpOutboxPublisher(
        destination_uri=req.destination_uri,
        endpoint_url=req.endpoint_url,
    )


def _build_amqp_publisher(req: PublisherBuildRequest) -> MessagePublisherPort:
    return AmqpPublisherAdapter(use_in_memory=req.use_in_memory)


def _build_kafka_consumer(req: ConsumerBuildRequest) -> ConsumerManagerPort:
    servers = req.bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS") or "localhost:9092"
    return KafkaConsumerManager(
        topic=req.source_uri,
        group_id=req.group_id,
        handler=req.handler,
        bootstrap_servers=servers,
    )


def _build_kafka_outbox_publisher(req: OutboxPublisherBuildRequest) -> OutboxPublisherPort:
    servers = req.bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS") or "localhost:9092"
    return KafkaOutboxPublisher(
        topic=req.destination_uri,
        bootstrap_servers=servers,
    )


def _build_kafka_publisher(req: PublisherBuildRequest) -> MessagePublisherPort:
    servers = req.bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS") or "localhost:9092"
    return KafkaPublisherAdapter(
        bootstrap_servers=servers,
        use_in_memory=req.use_in_memory,
    )


def _build_sqs_consumer(req: ConsumerBuildRequest) -> ConsumerManagerPort:
    queue_url = req.source_uri.removeprefix(f"{BrokerType.SQS.value}://")
    consumer = AwsSqsConsumer(
        queue_url=queue_url,
        region_name=req.region_name,
        endpoint_url=req.endpoint_url,
    )
    queue_name = queue_url.rsplit("/", 1)[-1]
    return AwsSqsConsumerManager(
        consumer=consumer,
        handler=req.handler,
        queue_name=queue_name,
        poll_sleep_seconds=req.poll_sleep_seconds,
        error_sleep_seconds=req.error_sleep_seconds,
        error_handler=req.error_handler,
    )


def _build_sqs_outbox_publisher(req: OutboxPublisherBuildRequest) -> OutboxPublisherPort:
    queue_url = req.destination_uri.removeprefix(f"{BrokerType.SQS.value}://")
    return AwsSqsOutboxPublisher(
        queue_url=queue_url,
        region_name=req.region_name,
        endpoint_url=req.endpoint_url,
        max_concurrent_batches=req.max_concurrent_batches,
    )


def _build_sns_outbox_publisher(req: OutboxPublisherBuildRequest) -> OutboxPublisherPort:
    topic_arn = req.destination_uri.removeprefix(f"{BrokerType.SNS.value}://")
    return AwsSnsOutboxPublisher(
        topic_arn=topic_arn,
        region_name=req.region_name,
        endpoint_url=req.endpoint_url,
        max_concurrent_batches=req.max_concurrent_batches,
    )


def _build_aws_publisher(req: PublisherBuildRequest) -> MessagePublisherPort:
    return AwsMessagePublisherAdapter(
        region_name=req.region_name,
        endpoint_url=req.endpoint_url,
    )


@lru_cache(maxsize=1)
def create_default_broker_registry() -> BrokerTransportRegistry:
    """Assembles and freezes the standard platform broker registry with built-in plugins."""
    registry = BrokerTransportRegistry()
    registry.register(
        BrokerTransportSpec(
            name=BrokerType.DB.value,
            uri_prefixes=DATABASE_QUEUE_SCHEMES,
            remedy=(
                "Update queue/topic environment variables to db://... "
                "(run 'pnpm infra:sync-topology' and 'direnv reload' or open a fresh shell "
                "if stale shell variables are exported)."
            ),
            endpoint_family=None,
            build_consumer=_build_database_consumer,
            build_outbox_publisher=_build_database_outbox_publisher,
            build_publisher=_build_database_publisher,
        )
    )
    registry.register(
        BrokerTransportSpec(
            name=BrokerType.MEMORY.value,
            uri_prefixes=(f"{BrokerType.MEMORY.value}://",),
            remedy="Update broker environment variables to in-memory URIs (memory://...).",
            endpoint_family=None,
            build_consumer=_build_memory_consumer,
            build_outbox_publisher=_build_memory_outbox_publisher,
            build_publisher=_build_memory_publisher,
        )
    )
    registry.register(
        BrokerTransportSpec(
            name=BrokerType.AMQP.value,
            uri_prefixes=AMQP_QUEUE_SCHEMES,
            remedy="Update broker environment variables to AMQP URIs (amqp:// or amqps://...).",
            endpoint_family=None,
            build_consumer=_build_amqp_consumer,
            build_outbox_publisher=_build_amqp_outbox_publisher,
            build_publisher=_build_amqp_publisher,
        )
    )
    registry.register(
        BrokerTransportSpec(
            name=BrokerType.KAFKA.value,
            uri_prefixes=(f"{BrokerType.KAFKA.value}://",),
            remedy="Update broker environment variables to Kafka URIs (kafka://...).",
            endpoint_family=None,
            build_consumer=_build_kafka_consumer,
            build_outbox_publisher=_build_kafka_outbox_publisher,
            build_publisher=_build_kafka_publisher,
        )
    )
    registry.register(
        BrokerTransportSpec(
            name=BrokerType.SQS.value,
            uri_prefixes=(f"{BrokerType.SQS.value}://", "https://", "http://"),
            remedy="Update queue environment variables to SQS URIs (sqs://, https://, or http://).",
            endpoint_family=_AWS_ENDPOINT_FAMILY,
            build_consumer=_build_sqs_consumer,
            build_outbox_publisher=_build_sqs_outbox_publisher,
            build_publisher=_build_aws_publisher,
        )
    )
    registry.register(
        BrokerTransportSpec(
            name=BrokerType.SNS.value,
            uri_prefixes=(f"{BrokerType.SNS.value}://", "arn:aws:sns:"),
            remedy="Update topic environment variables to SNS URIs (sns:// or arn:aws:sns:...).",
            endpoint_family=_AWS_ENDPOINT_FAMILY,
            build_consumer=None,
            build_outbox_publisher=_build_sns_outbox_publisher,
            build_publisher=_build_aws_publisher,
        )
    )
    registry.register_policy_group(
        BrokerPolicyGroup(
            name=_AWS_POLICY_GROUP,
            member_names=frozenset({BrokerType.SQS.value, BrokerType.SNS.value}),
            remedy=(
                "Update queue/topic environment variables to AWS SQS URLs (sqs:// or https://...) "
                "or SNS topic ARNs (sns:// or arn:aws:sns:...)."
            ),
            endpoint_family=_AWS_ENDPOINT_FAMILY,
        )
    )
    return registry.freeze()


class PubSubProvider:
    """Universal Platform Composition Root for Pub/Sub publishers and consumer pumps.

    All broker routing and transport policy enforcement are delegated to the Open-Closed
    ``BrokerTransportRegistry``. Adding a new message queue requires only registering a
    ``BrokerTransportSpec`` — never modifying ``PubSubProvider`` or ``seedwork``.
    """

    @classmethod
    def default_registry(cls) -> BrokerTransportRegistry:
        """Returns the default platform broker transport registry."""
        return create_default_broker_registry()

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
        transport: str | None = None,
        registry: BrokerTransportRegistry | None = None,
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
        """Creates an autonomous background consumer pump via the registered broker plugin."""
        if use_in_memory:
            return InMemoryConsumerManager(source_uri=source_uri, handler=handler)

        active_registry = registry or cls.default_registry()
        has_injected_db_source = (
            shard_drain_repo is not None
            or global_outbox_repo is not None
            or database_queue is not None
        )
        matched_spec = (
            active_registry.get_spec(BrokerType.DB.value)
            if has_injected_db_source
            else active_registry.resolve_uri(source_uri)
        )
        active_registry.enforce_policy(
            source_uri,
            transport=transport,
            matched_spec=matched_spec,
        )
        if matched_spec is None or matched_spec.build_consumer is None:
            raise UnsupportedBrokerSchemeError(
                extract_uri_scheme_label(source_uri),
                supported_prefixes=active_registry.supported_prefixes(),
            )

        request = ConsumerBuildRequest(
            source_uri=source_uri,
            handler=handler,
            group_id=group_id,
            region_name=region_name,
            endpoint_url=endpoint_url,
            bootstrap_servers=bootstrap_servers,
            use_in_memory=use_in_memory,
            error_handler=error_handler,
            poll_sleep_seconds=poll_sleep_seconds,
            error_sleep_seconds=error_sleep_seconds,
            shard_drain_repo=shard_drain_repo,
            dlq_publisher=dlq_publisher,
            global_outbox_repo=global_outbox_repo,
            database_queue=database_queue,
            session_factory=session_factory,
            database_url=database_url,
            subscribe_topics=subscribe_topics,
            dispatch_mode=dispatch_mode,
            batch_size=batch_size,
            lock_lease_ms=lock_lease_ms,
        )
        return matched_spec.build_consumer(request)

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
        transport: str | None = None,
        registry: BrokerTransportRegistry | None = None,
        max_concurrent_batches: int = 10,
        database_queue: DatabaseQueuePort | None = None,
        session_factory: SessionScopeFactory | None = None,
        database_url: str | None = None,
    ) -> OutboxPublisherPort:
        """Creates a destination-bound OutboxPublisherPort via the registered broker plugin."""
        if use_in_memory:
            return InMemoryOutboxPublisher(destination_uri=destination_uri)

        active_registry = registry or cls.default_registry()
        matched_spec = active_registry.resolve_uri(destination_uri)
        active_registry.enforce_policy(
            destination_uri,
            transport=transport,
            matched_spec=matched_spec,
        )
        if matched_spec is None or matched_spec.build_outbox_publisher is None:
            raise UnsupportedBrokerSchemeError(
                extract_uri_scheme_label(destination_uri),
                supported_prefixes=active_registry.supported_prefixes(),
            )

        request = OutboxPublisherBuildRequest(
            destination_uri=destination_uri,
            region_name=region_name,
            endpoint_url=endpoint_url,
            bootstrap_servers=bootstrap_servers,
            use_in_memory=use_in_memory,
            max_concurrent_batches=max_concurrent_batches,
            database_queue=database_queue,
            session_factory=session_factory,
            database_url=database_url,
        )
        return matched_spec.build_outbox_publisher(request)

    @classmethod
    def create_publisher(
        cls,
        destination_uri: str,
        *,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
        bootstrap_servers: str | None = None,
        use_in_memory: bool = False,
        transport: str | None = None,
        registry: BrokerTransportRegistry | None = None,
        database_queue: DatabaseQueuePort | None = None,
        session_factory: SessionScopeFactory | None = None,
        database_url: str | None = None,
    ) -> MessagePublisherPort:
        """Creates a direct MessagePublisherPort via the registered broker plugin."""
        if use_in_memory:
            return InMemoryPublisherAdapter()

        active_registry = registry or cls.default_registry()
        matched_spec = active_registry.resolve_uri(destination_uri)
        active_registry.enforce_policy(
            destination_uri,
            transport=transport,
            matched_spec=matched_spec,
        )
        if matched_spec is None or matched_spec.build_publisher is None:
            raise UnsupportedBrokerSchemeError(
                extract_uri_scheme_label(destination_uri),
                supported_prefixes=active_registry.supported_prefixes(),
            )

        request = PublisherBuildRequest(
            destination_uri=destination_uri,
            region_name=region_name,
            endpoint_url=endpoint_url,
            bootstrap_servers=bootstrap_servers,
            use_in_memory=use_in_memory,
            database_queue=database_queue,
            session_factory=session_factory,
            database_url=database_url,
        )
        return matched_spec.build_publisher(request)
