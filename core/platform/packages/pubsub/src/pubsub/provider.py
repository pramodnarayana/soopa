from collections.abc import Awaitable, Callable

from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.domain.types import JsonDict

from pubsub.aws.aws_sns_publisher import AwsSnsPublisher
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.aws_sqs_publisher import AwsSqsPublisher
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager


class PubSubProvider:
    """
    Centralized Platform Provider for Pub/Sub publishers and consumers.

    This is the single place where bounded contexts obtain broker adapters, so worker
    composition roots never construct AWS classes themselves.

    TODO(tech-debt): This provider is currently tightly coupled with AWS implementations
    (SQS/SNS). To achieve a true vendor-neutral Hexagonal Architecture, this class should
    be refactored to return generic publisher/consumer abstractions without leaking AWS
    specifics into the creation signatures, allowing seamless swapping to Google Pub/Sub
    or Kafka in the future.

    Providers only create single-destination publishers and consumers. Deciding *which*
    destination an event goes to is application logic and lives in the owning bounded context.
    """

    @classmethod
    def create_queue_publisher(
        cls,
        queue_url: str,
        region_name: str,
        endpoint_url: str | None = None,
    ) -> OutboxPublisherPort:
        """Creates a publisher that sends every event to a single queue."""
        return AwsSqsPublisher(
            queue_url=queue_url,
            region_name=region_name,
            endpoint_url=endpoint_url,
        )

    @classmethod
    def create_topic_publisher(
        cls,
        topic_arn: str,
        region_name: str,
        endpoint_url: str | None = None,
    ) -> OutboxPublisherPort:
        """Creates a publisher that fans every event out through a single topic."""
        return AwsSnsPublisher(
            topic_arn=topic_arn,
            region_name=region_name,
            endpoint_url=endpoint_url,
        )

    @classmethod
    def create_consumer_manager(
        cls,
        queue_url: str,
        handler: Callable[[JsonDict], Awaitable[None]],
        region_name: str,
        endpoint_url: str | None = None,
    ) -> SqsConsumerManager:
        """Creates a message pump that polls a single queue and dispatches to ``handler``."""
        consumer = AwsSqsConsumer(
            queue_url=queue_url,
            region_name=region_name,
            endpoint_url=endpoint_url,
        )
        return SqsConsumerManager(
            consumer=consumer,
            queue_name=queue_url.rsplit("/", 1)[-1],
            handler=handler,
        )
