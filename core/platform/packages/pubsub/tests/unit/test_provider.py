from pubsub.adapters.aws.aws_sns_outbox_publisher import AwsSnsOutboxPublisher
from pubsub.adapters.aws.aws_sqs_consumer_manager import AwsSqsConsumerManager
from pubsub.adapters.aws.aws_sqs_outbox_publisher import AwsSqsOutboxPublisher
from pubsub.adapters.kafka.kafka_consumer_manager import KafkaConsumerManager
from pubsub.adapters.kafka.kafka_outbox_publisher import KafkaOutboxPublisher
from pubsub.adapters.memory.in_memory_consumer_manager import InMemoryConsumerManager
from pubsub.adapters.memory.in_memory_outbox_publisher import InMemoryOutboxPublisher
from pubsub.enums import ConsumerAction
from pubsub.provider import PubSubProvider


def test_pubsub_provider_creates_sqs_outbox_publisher() -> None:
    pub = PubSubProvider.create_outbox_publisher(
        destination_uri="https://sqs.us-east-1.amazonaws.com/123/my-queue",
        region_name="us-east-1",
        endpoint_url="http://localhost:4566",
    )
    assert isinstance(pub, AwsSqsOutboxPublisher)
    assert pub.queue_url == "https://sqs.us-east-1.amazonaws.com/123/my-queue"
    assert pub.region_name == "us-east-1"


def test_pubsub_provider_creates_sns_outbox_publisher() -> None:
    pub = PubSubProvider.create_outbox_publisher(
        destination_uri="arn:aws:sns:us-east-1:123:my-topic",
        region_name="us-east-1",
    )
    assert isinstance(pub, AwsSnsOutboxPublisher)
    assert pub.topic_arn == "arn:aws:sns:us-east-1:123:my-topic"
    assert pub.region_name == "us-east-1"


def test_pubsub_provider_creates_kafka_outbox_publisher() -> None:
    pub = PubSubProvider.create_outbox_publisher(
        destination_uri="kafka://my-topic",
        bootstrap_servers="localhost:9092",
    )
    assert isinstance(pub, KafkaOutboxPublisher)
    assert pub.topic == "my-topic"


def test_pubsub_provider_creates_memory_outbox_publisher() -> None:
    pub = PubSubProvider.create_outbox_publisher(destination_uri="memory://test")
    assert isinstance(pub, InMemoryOutboxPublisher)


def test_pubsub_provider_creates_sqs_consumer_manager() -> None:
    async def dummy_handler(msg: object) -> ConsumerAction:
        return ConsumerAction.ACK

    manager = PubSubProvider.create_consumer_manager(
        source_uri="https://sqs.us-east-1.amazonaws.com/123/orders-queue",
        handler=dummy_handler,
        region_name="us-east-1",
    )
    assert isinstance(manager, AwsSqsConsumerManager)
    assert manager.queue_name == "orders-queue"


def test_pubsub_provider_creates_kafka_consumer_manager() -> None:
    async def dummy_handler(msg: object) -> ConsumerAction:
        return ConsumerAction.ACK

    manager = PubSubProvider.create_consumer_manager(
        source_uri="kafka://orders",
        handler=dummy_handler,
        group_id="test-grp",
    )
    assert isinstance(manager, KafkaConsumerManager)
    assert manager._topic == "orders"


def test_pubsub_provider_creates_memory_consumer_manager() -> None:
    async def dummy_handler(msg: object) -> ConsumerAction:
        return ConsumerAction.ACK

    manager = PubSubProvider.create_consumer_manager(
        source_uri="memory://orders",
        handler=dummy_handler,
    )
    assert isinstance(manager, InMemoryConsumerManager)
