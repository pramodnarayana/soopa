from __future__ import annotations

import pytest
from pubsub.adapters.aws.aws_sns_outbox_publisher import AwsSnsOutboxPublisher
from pubsub.adapters.aws.aws_sqs_consumer_manager import AwsSqsConsumerManager
from pubsub.adapters.aws.aws_sqs_outbox_publisher import AwsSqsOutboxPublisher
from pubsub.adapters.kafka.kafka_consumer_manager import KafkaConsumerManager
from pubsub.adapters.kafka.kafka_outbox_publisher import KafkaOutboxPublisher
from pubsub.adapters.memory.in_memory_consumer_manager import InMemoryConsumerManager
from pubsub.adapters.memory.in_memory_outbox_publisher import InMemoryOutboxPublisher
from pubsub.adapters.memory.in_memory_publisher_adapter import InMemoryPublisherAdapter
from pubsub.config import PlatformPubSubSettings
from pubsub.domain.exceptions import (
    BrokerTransportMismatchError,
    InvalidBrokerTransportError,
    UnsupportedBrokerSchemeError,
)
from pubsub.enums import ConsumerAction
from pubsub.provider import PubSubProvider
from pubsub.registry import (
    BrokerTransportSpec,
    ConsumerBuildRequest,
    OutboxPublisherBuildRequest,
    PublisherBuildRequest,
    TransportPolicyViolation,
)


async def _dummy_handler(_msg: object) -> ConsumerAction:
    return ConsumerAction.ACK


def test_pubsub_provider_creates_sqs_outbox_publisher() -> None:
    pub = PubSubProvider.create_outbox_publisher(
        destination_uri="https://sqs.us-east-1.amazonaws.com/123/my-queue",
        region_name="us-east-1",
        endpoint_url="http://localhost:4566",
        transport="aws",
    )
    assert isinstance(pub, AwsSqsOutboxPublisher)
    assert pub.queue_url == "https://sqs.us-east-1.amazonaws.com/123/my-queue"
    assert pub.region_name == "us-east-1"


def test_pubsub_provider_creates_sns_outbox_publisher() -> None:
    pub = PubSubProvider.create_outbox_publisher(
        destination_uri="arn:aws:sns:us-east-1:123:my-topic",
        region_name="us-east-1",
        transport="aws",
    )
    assert isinstance(pub, AwsSnsOutboxPublisher)
    assert pub.topic_arn == "arn:aws:sns:us-east-1:123:my-topic"
    assert pub.region_name == "us-east-1"


def test_pubsub_provider_creates_kafka_outbox_publisher() -> None:
    pub = PubSubProvider.create_outbox_publisher(
        destination_uri="kafka://my-topic",
        bootstrap_servers="localhost:9092",
        transport="kafka",
    )
    assert isinstance(pub, KafkaOutboxPublisher)
    assert pub.topic == "my-topic"


def test_pubsub_provider_creates_memory_outbox_publisher() -> None:
    pub = PubSubProvider.create_outbox_publisher(destination_uri="memory://test")
    assert isinstance(pub, InMemoryOutboxPublisher)


def test_pubsub_provider_creates_sqs_consumer_manager() -> None:
    manager = PubSubProvider.create_consumer_manager(
        source_uri="https://sqs.us-east-1.amazonaws.com/123/orders-queue",
        handler=_dummy_handler,
        region_name="us-east-1",
        transport="aws",
    )
    assert isinstance(manager, AwsSqsConsumerManager)
    assert manager.queue_name == "orders-queue"


def test_pubsub_provider_creates_kafka_consumer_manager() -> None:
    manager = PubSubProvider.create_consumer_manager(
        source_uri="kafka://orders",
        handler=_dummy_handler,
        group_id="test-grp",
        transport="kafka",
    )
    assert isinstance(manager, KafkaConsumerManager)
    assert manager._topic == "orders"


def test_pubsub_provider_creates_memory_consumer_manager() -> None:
    manager = PubSubProvider.create_consumer_manager(
        source_uri="memory://orders",
        handler=_dummy_handler,
    )
    assert isinstance(manager, InMemoryConsumerManager)


def test_pubsub_provider_enforces_symmetric_transport_policy() -> None:
    # 1. db transport rejects stale LocalStack / SQS URIs
    with pytest.raises(BrokerTransportMismatchError, match="PUBSUB_TRANSPORT='db'"):
        PubSubProvider.create_consumer_manager(
            source_uri="http://localhost:4566/000000000000/notifications.fifo",
            handler=_dummy_handler,
            endpoint_url="http://localhost:4566",
            transport="db",
        )

    # 2. aws transport symmetrically rejects db:// URIs
    with pytest.raises(BrokerTransportMismatchError, match="PUBSUB_TRANSPORT='aws'"):
        PubSubProvider.create_consumer_manager(
            source_uri="db://notifications.fifo",
            handler=_dummy_handler,
            transport="aws",
        )

    # 3. kafka transport symmetrically rejects SQS URIs
    with pytest.raises(BrokerTransportMismatchError, match="PUBSUB_TRANSPORT='kafka'"):
        PubSubProvider.create_outbox_publisher(
            destination_uri="https://sqs.us-east-1.amazonaws.com/123/my-queue",
            transport="kafka",
        )

    # 4. unrecognized transport fails fast
    with pytest.raises(InvalidBrokerTransportError, match="Unsupported PUBSUB_TRANSPORT='bogus'"):
        PubSubProvider.create_consumer_manager(
            source_uri="db://notifications.fifo",
            handler=_dummy_handler,
            transport="bogus",
        )


def test_pubsub_provider_fails_closed_on_unknown_scheme_across_all_factories() -> None:
    # Even when the URI contains the word "queue", strict prefix resolution rejects it.
    with pytest.raises(UnsupportedBrokerSchemeError):
        PubSubProvider.create_consumer_manager(
            source_uri="bogus://my-queue.fifo",
            handler=_dummy_handler,
        )
    with pytest.raises(UnsupportedBrokerSchemeError):
        PubSubProvider.create_outbox_publisher(destination_uri="bogus://my-queue.fifo")
    with pytest.raises(UnsupportedBrokerSchemeError):
        PubSubProvider.create_publisher(destination_uri="bogus://my-queue.fifo")


def test_default_registry_is_frozen_and_check_policy_returns_first_class_violation() -> None:
    default_registry = PubSubProvider.default_registry()
    assert default_registry.is_frozen is True

    with pytest.raises(RuntimeError, match="Cannot mutate a frozen BrokerTransportRegistry"):
        default_registry.register(BrokerTransportSpec(name="nats", uri_prefixes=("nats://",)))

    violation = default_registry.check_policy(
        "http://localhost:4566/000000000000/notifications.fifo",
        transport="db",
    )
    assert isinstance(violation, TransportPolicyViolation)
    assert violation.transport == "db"
    assert violation.matched_transport == "sqs"
    assert default_registry.check_policy("db://notifications.fifo", transport="db") is None


def test_ocp_custom_broker_plugin_works_without_modifying_provider_or_settings() -> None:
    """Proves Open-Closed extensibility: registering NATS works across Provider and Settings."""
    registry = PubSubProvider.default_registry().copy()
    assert registry.is_frozen is False

    def build_nats_consumer(req: ConsumerBuildRequest) -> InMemoryConsumerManager:
        return InMemoryConsumerManager(source_uri=req.source_uri, handler=req.handler)

    def build_nats_outbox(req: OutboxPublisherBuildRequest) -> InMemoryOutboxPublisher:
        return InMemoryOutboxPublisher(destination_uri=req.destination_uri)

    def build_nats_pub(_req: PublisherBuildRequest) -> InMemoryPublisherAdapter:
        return InMemoryPublisherAdapter()

    registry.register(
        BrokerTransportSpec(
            name="nats",
            uri_prefixes=("nats://",),
            remedy="Configure NATS JetStream subjects as nats://<subject>.",
            endpoint_family="nats",
            build_consumer=build_nats_consumer,
            build_outbox_publisher=build_nats_outbox,
            build_publisher=build_nats_pub,
        )
    )

    # 1. Settings validate NATS URIs and reject mismatched URIs using the extended registry
    settings = PlatformPubSubSettings(_env_file=None, PUBSUB_TRANSPORT="nats")
    settings.validate_uris({"SUBJECT": "nats://orders.created"}, registry=registry)
    assert settings.effective_aws_endpoint_url("http://localhost:4566", registry=registry) is None
    assert (
        settings.effective_endpoint_url("nats://127.0.0.1:4222", family="nats", registry=registry)
        == "nats://127.0.0.1:4222"
    )

    with pytest.raises(ValueError, match="PUBSUB_TRANSPORT='nats'"):
        settings.validate_uris({"SUBJECT": "db://orders"}, registry=registry)

    # 2. Provider dispatches to NATS plugin and enforces policy symmetrically
    consumer = PubSubProvider.create_consumer_manager(
        source_uri="nats://orders.created",
        handler=_dummy_handler,
        transport="nats",
        registry=registry,
    )
    assert isinstance(consumer, InMemoryConsumerManager)

    with pytest.raises(BrokerTransportMismatchError, match="PUBSUB_TRANSPORT='nats'"):
        PubSubProvider.create_publisher(
            destination_uri="db://orders",
            transport="nats",
            registry=registry,
        )
