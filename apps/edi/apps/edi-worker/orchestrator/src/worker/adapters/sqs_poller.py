import asyncio
import json
from collections.abc import Callable
from typing import Any

import aioboto3
import structlog

logger = structlog.get_logger(__name__)


async def _process_message_task(
    queue_name: str,
    msg: dict[str, Any],
    processor_func: Callable[[dict[str, Any]], Any],
) -> str | None:
    """Processes a message and returns its ReceiptHandle if successful to be batch-deleted."""
    receipt_handle = str(msg["ReceiptHandle"])
    try:
        body = json.loads(msg["Body"])

        trace_id = body.get("payload", {}).get("trace_id")
        if trace_id:
            logger.info("processing_message", queue_name=queue_name, trace_id=trace_id)
        else:
            logger.info("processing_message", queue_name=queue_name)

        await processor_func(body)

        if trace_id:
            logger.info(
                "message_processed_successfully", queue_name=queue_name, trace_id=trace_id
            )
        else:
            logger.info("message_processed_successfully", queue_name=queue_name)

        return receipt_handle

    except json.JSONDecodeError:
        logger.exception("non_json_message_body_deleting_permanently", queue_name=queue_name)
        return receipt_handle  # Delete malformed messages

    except Exception:
        logger.exception("transient_error_processing_message", queue_name=queue_name)
        return None  # Do not delete, let it return to queue


async def _poll_loop(
    sqs: Any,
    queue_name: str,
    queue_url: str,
    processor_func: Callable[[dict[str, Any]], Any],
) -> None:
    logger.info("started_polling_queue", queue_name=queue_name, queue_url=queue_url)

    while True:
        try:
            response = await sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=20,
            )

            messages = response.get("Messages", [])
            if not messages:
                continue

            # Process all messages concurrently
            tasks = [
                _process_message_task(queue_name, msg, processor_func)
                for msg in messages
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Collect successful receipt handles for batch deletion
            successful_handles = []
            for result in results:
                if isinstance(result, str):
                    successful_handles.append(result)

            if successful_handles:
                entries = [
                    {"Id": str(i), "ReceiptHandle": handle}
                    for i, handle in enumerate(successful_handles)
                ]
                await sqs.delete_message_batch(QueueUrl=queue_url, Entries=entries)

        except Exception:
            logger.exception("sqs_client_error_retrying", queue_name=queue_name)
            await asyncio.sleep(2)


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

                await _poll_loop(sqs, queue_name, queue_url, processor_func)

        except Exception:
            logger.exception(
                "sqs_client_or_queue_initialization_failed_retrying", queue_name=queue_name
            )
            await asyncio.sleep(5)
