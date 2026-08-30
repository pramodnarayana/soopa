import json
from typing import Any

import aioboto3
import structlog

from edi.ports.outbound.message_queue import MessageQueuePort

logger = structlog.get_logger(__name__)


class SQSMessageQueueAdapter(MessageQueuePort):
    """
    SQS Adapter implementation of the MessageQueuePort.
    Handles all AWS-specific infrastructure logic.
    """

    def __init__(
        self,
        queue_url_map: dict[str, str],
        endpoint_url: str | None = None,
        region: str = "us-east-1",
    ):
        self.queue_url_map = queue_url_map
        self.endpoint_url = endpoint_url
        self.region = region
        self.session = aioboto3.Session()

    async def send(self, queue_name: str, payload: dict[str, Any]) -> None:
        logger.info("Relaying event to SQS queue '{queue_name}'", queue_name=queue_name)

        queue_url = self.queue_url_map.get(queue_name)
        if not queue_url:
            raise ValueError(f"Queue URL not configured for queue name: {queue_name}")

        client_kwargs = {"region_name": self.region}
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url

        async with self.session.client("sqs", **client_kwargs) as sqs:
            # Send message to SQS
            await sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(payload))

            logger.info(
                "Successfully sent message to SQS queue {queue_name}", queue_name=queue_name
            )
