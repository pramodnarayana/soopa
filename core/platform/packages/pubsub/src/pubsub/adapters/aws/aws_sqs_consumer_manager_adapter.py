"""AWS SQS Consumer Manager Adapter alias."""

from pubsub.adapters.aws.aws_sqs_consumer_manager import (
    AwsSqsConsumerManager,
)
from pubsub.adapters.aws.aws_sqs_consumer_manager import (
    AwsSqsConsumerManager as AwsSqsConsumerManagerAdapter,
)

__all__ = ["AwsSqsConsumerManager", "AwsSqsConsumerManagerAdapter"]
