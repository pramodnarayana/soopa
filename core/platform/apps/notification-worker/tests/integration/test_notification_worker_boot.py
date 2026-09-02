import asyncio
import os

import boto3
import pytest

from notification_worker.bootstrap.container import WorkerContainer
from notification_worker.main import run_consumer


@pytest.mark.asyncio
async def test_notification_worker_boots_and_shuts_down_gracefully() -> None:
    """
    Narrow Integration Test (E2E) that verifies the notification worker container
    can successfully wire its real infrastructure dependencies (Postgres, SQS, SNS)
    and then shut them down gracefully.
    """

    # Ensure queues exist in LocalStack for the test
    sqs = boto3.client(
        "sqs",
        endpoint_url="http://localhost:4566",
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",  # noqa: S106
    )

    sqs.create_queue(
        QueueName="edi-priority-notifications.fifo",
        Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "true"},
    )
    sqs.create_queue(
        QueueName="email-delivery.fifo",
        Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "true"},
    )

    # Create the stop event that we'll use to gracefully shut down the worker
    stop_event = asyncio.Event()

    # Pass in the correct settings for the integration test environment
    container = WorkerContainer()
    container.config.database_url.from_value(
        "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
    )
    container.config.sns_topic_arn.from_value(
        "arn:aws:sns:us-east-1:000000000000:identity-events-topic"
    )
    container.config.priority_queue_url.from_value(
        "http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/edi-priority-notifications.fifo"
    )
    container.config.email_delivery_queue_url.from_value(
        "http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/email-delivery.fifo"
    )
    container.config.aws_endpoint_url.from_value("http://localhost:4566")
    container.config.aws_region.from_value("us-east-1")

    credential_keys = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
    original_credentials = {key: os.environ.get(key) for key in credential_keys}
    try:
        # We set these in environ as well for any internal boto3 clients that might rely on them
        os.environ["AWS_ACCESS_KEY_ID"] = "test"
        os.environ["AWS_SECRET_ACCESS_KEY"] = "test"  # noqa: S105

        # Start the worker in the background
        worker_task = asyncio.create_task(run_consumer(stop_event=stop_event, container=container))

        try:
            # Give it a second to boot up all infrastructure listeners and consumers
            await asyncio.sleep(1.0)
        finally:
            # Trigger the graceful shutdown
            stop_event.set()

        # Await the worker shutdown (with a timeout so we don't hang if it's stuck)
        await asyncio.wait_for(worker_task, timeout=5.0)
    finally:
        for key, original_value in original_credentials.items():
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value
