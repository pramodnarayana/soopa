import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import aioboto3  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


async def poll_sqs_queue(
    queue_name: str,
    processor_func: Callable[[dict[str, Any]], Any],
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

                            # Log trace_id if available, otherwise just log processing
                            trace_id = body.get("payload", {}).get("trace_id")
                            if trace_id:
                                logger.info(f"[{queue_name}] Processing trace_id={trace_id}")
                            else:
                                logger.info(f"[{queue_name}] Processing message")

                            await processor_func(body)

                            # Delete message on success
                            await sqs.delete_message(
                                QueueUrl=queue_url, ReceiptHandle=receipt_handle
                            )

                            if trace_id:
                                logger.info(
                                    f"[{queue_name}] Successfully processed trace_id={trace_id}"
                                )
                            else:
                                logger.info(f"[{queue_name}] Successfully processed message")

                        except json.JSONDecodeError:
                            # Permanently delete malformed (non-JSON) messages
                            logger.error(
                                f"[{queue_name}] Non-JSON message body, deleting permanently"
                            )
                            await sqs.delete_message(
                                QueueUrl=queue_url, ReceiptHandle=receipt_handle
                            )

                        except Exception as e:
                            logger.exception(
                                f"[{queue_name}] Transient error processing message: {e}"
                            )
        except Exception as e:
            logger.exception(f"[{queue_name}] SQS client error, retrying in 2s: {e}")
            await asyncio.sleep(2)
