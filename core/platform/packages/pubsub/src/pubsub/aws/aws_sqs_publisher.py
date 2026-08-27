from typing import ClassVar

from pubsub.aws.aws_batch_publisher_base import AwsBatchPublisherBase


class AwsSqsPublisher(AwsBatchPublisherBase):
    """Generic publisher that sends outbox events to an AWS SQS queue."""

    service_name: ClassVar[str] = "sqs"
    destination_parameter: ClassVar[str] = "QueueUrl"
    single_method: ClassVar[str] = "send_message"
    batch_method: ClassVar[str] = "send_message_batch"
    batch_entries_parameter: ClassVar[str] = "Entries"
    message_parameter: ClassVar[str] = "MessageBody"
    destination_error: ClassVar[str] = "sqs_queue_url_not_configured"

    def __init__(
        self,
        queue_url: str,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
    ) -> None:
        super().__init__(queue_url, region_name, endpoint_url)
        self.queue_url = queue_url
