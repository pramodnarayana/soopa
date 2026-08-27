from typing import ClassVar

from pubsub.aws.aws_batch_publisher_base import AwsBatchPublisherBase


class AwsSnsPublisher(AwsBatchPublisherBase):
    """Generic publisher that sends outbox events to an AWS SNS topic."""

    service_name: ClassVar[str] = "sns"
    destination_parameter: ClassVar[str] = "TopicArn"
    single_method: ClassVar[str] = "publish"
    batch_method: ClassVar[str] = "publish_batch"
    batch_entries_parameter: ClassVar[str] = "PublishBatchRequestEntries"
    message_parameter: ClassVar[str] = "Message"
    destination_error: ClassVar[str] = "sns_topic_arn_not_configured"

    def __init__(
        self,
        topic_arn: str,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
    ) -> None:
        super().__init__(topic_arn, region_name, endpoint_url)
        self.topic_arn = topic_arn
