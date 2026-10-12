from pubsub.aws.aws_sns_publisher import AwsSnsPublisher
from pubsub.aws.aws_sqs_publisher import AwsSqsPublisher
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.enums import ConsumerAction
from pubsub.provider import PubSubProvider


def test_pubsub_provider_creates_queue_publisher() -> None:
    pub = PubSubProvider.create_queue_publisher(
        queue_url="https://sqs.us-east-1.amazonaws.com/123/my-queue",
        region_name="us-east-1",
        endpoint_url="http://localhost:4566",
    )
    assert isinstance(pub, AwsSqsPublisher)
    assert pub.queue_url == "https://sqs.us-east-1.amazonaws.com/123/my-queue"
    assert pub.region_name == "us-east-1"


def test_pubsub_provider_creates_topic_publisher() -> None:
    pub = PubSubProvider.create_topic_publisher(
        topic_arn="arn:aws:sns:us-east-1:123:my-topic",
        region_name="us-east-1",
    )
    assert isinstance(pub, AwsSnsPublisher)
    assert pub.topic_arn == "arn:aws:sns:us-east-1:123:my-topic"
    assert pub.region_name == "us-east-1"


def test_pubsub_provider_creates_consumer_manager() -> None:
    async def dummy_handler(msg: object) -> ConsumerAction:
        return ConsumerAction.ACK

    manager = PubSubProvider.create_consumer_manager(
        queue_url="https://sqs.us-east-1.amazonaws.com/123/orders-queue",
        handler=dummy_handler,
        region_name="us-east-1",
    )
    assert isinstance(manager, SqsConsumerManager)
    assert manager.queue_name == "orders-queue"
