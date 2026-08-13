import asyncio
import json
from collections.abc import Callable
from typing import Any

import aioboto3
import structlog

logger = structlog.get_logger(__name__)


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

    try:
        async with session.client("sqs", **client_kwargs) as sqs:
            queue_url_resp = await sqs.get_queue_url(QueueName=queue_name)
            queue_url = queue_url_resp["QueueUrl"]

            logger.info("started_polling_queue", queue_name=queue_name, queue_url=queue_url)

            while True:
                try:
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
                                logger.info("processing_message", queue_name=queue_name, trace_id=trace_id)
                            else:
                                logger.info("processing_message", queue_name=queue_name)

                            await processor_func(body)

                            # Delete message on success
                            await sqs.delete_message(
                                QueueUrl=queue_url, ReceiptHandle=receipt_handle
                            )

                            if trace_id:
                                logger.info("message_processed_successfully", queue_name=queue_name, trace_id=trace_id)
                            else:
                                logger.info("message_processed_successfully", queue_name=queue_name)

                        except json.JSONDecodeError:
                            # Permanently delete malformed (non-JSON) messages
                            logger.exception("non_json_message_body_deleting_permanently", queue_name=queue_name)
                            await sqs.delete_message(
                                QueueUrl=queue_url, ReceiptHandle=receipt_handle
                            )

                        except Exception:
                            logger.exception("transient_error_processing_message", queue_name=queue_name)
                except Exception:
                    logger.exception("sqs_client_error_retrying", queue_name=queue_name)
                    await asyncio.sleep(2)
    except Exception:
        logger.exception("sqs_client_or_queue_initialization_failed")
