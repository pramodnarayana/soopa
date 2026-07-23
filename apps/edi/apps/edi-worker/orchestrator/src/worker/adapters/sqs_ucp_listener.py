import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import aioboto3
from botocore.exceptions import ClientError

from worker.ports.ucp_event_listener import UcpEventListenerPort, UcpEventMessage

logger = logging.getLogger(__name__)


class SqsUcpListenerAdapter(UcpEventListenerPort):
    def __init__(self, endpoint_url: str | None = None, queue_name: str = "ucp.events.fifo"):
        self.endpoint_url = endpoint_url
        self.queue_name = queue_name
        self.session = aioboto3.Session()

    @asynccontextmanager
    async def process_next_event(self) -> AsyncGenerator[UcpEventMessage | None, None]:
        async with self.session.client("sqs", endpoint_url=self.endpoint_url) as sqs_client:
            try:
                # Get the queue URL (could be cached in a real prod scenario)
                resp = await sqs_client.get_queue_url(QueueName=self.queue_name)
                queue_url = resp["QueueUrl"]

                response = await sqs_client.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=1,
                    WaitTimeSeconds=5,
                )

                messages = response.get("Messages", [])
                if not messages:
                    yield None
                    return

                msg = messages[0]
                receipt_handle = msg["ReceiptHandle"]
                body = msg["Body"]

                try:
                    sns_wrapper = json.loads(body)
                    event_str = sns_wrapper.get("Message", body)
                    event_data = json.loads(event_str)

                    event_message = UcpEventMessage.model_validate(event_data)

                    # Yield the message to the pure business logic
                    yield event_message

                    # If we return here without exception, the business logic succeeded.
                    # Delete the message to acknowledge successful processing.
                    await sqs_client.delete_message(
                        QueueUrl=queue_url, ReceiptHandle=receipt_handle
                    )

                except Exception as e:
                    logger.error(f"Failed to process or parse UCP event message: {e}")
                    # Re-raise to prevent deletion (message goes to DLQ or becomes visible again)
                    raise

            except ClientError as e:
                logger.error(f"SQS ClientError in UCP listener: {e}")
                raise
