import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aioboto3

logger = logging.getLogger(__name__)


async def poll_sqs_queue(
    queue_name: str,
    processor_func: Callable[[dict[str, Any]], Awaitable[Any]],
    aws_endpoint: str | None = None,
) -> None:
    """Long-polls an SQS queue and processes messages."""
    session = aioboto3.Session()
    client_kwargs = {"region_name": "us-east-1"}
    if aws_endpoint:
        client_kwargs["endpoint_url"] = aws_endpoint

    while True:
        try:
            async with session.client("sqs", **client_kwargs) as sqs:
                queue_url_resp = await sqs.get_queue_url(QueueName=queue_name)
                queue_url = queue_url_resp["QueueUrl"]

                logger.info(f"Started polling {queue_name} ({queue_url})")

                while True:
                    response = await sqs.receive_message(
                        QueueUrl=queue_url,
                        MaxNumberOfMessages=10,
                        WaitTimeSeconds=20,
                    )

                    messages = response.get("Messages", [])
                    for msg in messages:
                        receipt_handle = msg["ReceiptHandle"]
                        try:
                            body = json.loads(msg["Body"])

                            logger.info(f"[{queue_name}] Processing priority notification message")
                            await processor_func(body)

                            # Delete message on success
                            await sqs.delete_message(
                                QueueUrl=queue_url, ReceiptHandle=receipt_handle
                            )
                            logger.info(
                                f"[{queue_name}] Successfully processed and deleted message"
                            )

                        except json.JSONDecodeError:
                            # Permanently delete malformed (non-JSON) messages
                            logger.exception(
                                f"[{queue_name}] Non-JSON message body, deleting permanently"
                            )
                            await sqs.delete_message(
                                QueueUrl=queue_url, ReceiptHandle=receipt_handle
                            )

                        except Exception:
                            logger.exception(
                                "[%s] Error processing message, will retry", queue_name
                            )
        except Exception:
            logger.exception(f"[{queue_name}] SQS client error, retrying in 2s")
            await asyncio.sleep(2)
