"""
E2E-style tests for the SQS event consumer flow in identity-worker.

These tests verify the full dispatch chain: raw SQS payload → IdentityEventDispatcher
→ registered handler. The SqsConsumerManager is tested with a real AwsSqsConsumer
connected to LocalStack, complying with the strict enterprise testing rules.
"""

import asyncio
import os
from collections.abc import AsyncGenerator

import boto3
import pytest
from identity.domain.constants import IdentityEventType
from identity_worker.adapters.inbound.workers.identity_event_dispatcher import (
    IdentityEventDispatcher,
)
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from seedwork import generate_random_hex


@pytest.fixture(scope="session")
def event_loop() -> AsyncGenerator[asyncio.AbstractEventLoop, None]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
def localstack_sqs() -> dict[str, str]:
    endpoint_url = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")

    sqs_client = boto3.client(
        "sqs",
        endpoint_url=endpoint_url,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

    queue_name = f"identity-events-{generate_random_hex(6)}.fifo"

    queue = sqs_client.create_queue(
        QueueName=queue_name,
        Attributes={"FifoQueue": "true"},
    )

    queue_url = queue["QueueUrl"]

    yield {
        "endpoint_url": endpoint_url,
        "sqs_queue_url": queue_url,
        "sqs_queue_name": queue_name,
    }

    # Cleanup
    sqs_client.delete_queue(QueueUrl=queue_url)


@pytest.mark.asyncio
async def test_manager_dispatches_message_to_subscribed_handler(
    localstack_sqs: dict[str, str], monkeypatch: pytest.MonkeyPatch
):
    queue_url = localstack_sqs["sqs_queue_url"]
    endpoint_url = localstack_sqs["endpoint_url"]
    queue_name = localstack_sqs["sqs_queue_name"]

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    # 1. Inject a raw message directly into SQS
    sqs_client = boto3.client(
        "sqs",
        endpoint_url=endpoint_url,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

    test_payload = (
        '{"id": "evt_123", "source": "identity", '
        f'"event_type": "{IdentityEventType.TENANT_PROVISIONED}", '
        '"payload": {"tenant_id": "tenant-123"}}'
    )

    sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=test_payload,
        MessageGroupId="group_1",
        MessageDeduplicationId="dedup1",
    )

    # 2. Setup Dispatcher and Handler
    dispatcher = IdentityEventDispatcher()
    handled = asyncio.Event()

    async def handler(event) -> None:
        if event.event_type == IdentityEventType.TENANT_PROVISIONED:
            handled.set()

    dispatcher.subscribe(IdentityEventType.TENANT_PROVISIONED, handler)

    consumer_port = AwsSqsConsumer(
        queue_url=queue_url,
        region_name="us-east-1",
        endpoint_url=endpoint_url,
    )

    manager = SqsConsumerManager(
        consumer=consumer_port,
        queue_name=queue_name,
        handler=dispatcher.dispatch_raw,
    )

    # 3. Start Manager in a background task
    manager.start()

    # Wait for the handler to be triggered
    try:
        await asyncio.wait_for(handled.wait(), timeout=5.0)
    except TimeoutError:
        pytest.fail("Handler was never called by the SqsConsumerManager")
    finally:
        await manager.stop()

    # 4. Verify message was acked (deleted from queue)
    response = sqs_client.receive_message(
        QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=1
    )
    messages = response.get("Messages", [])
    assert len(messages) == 0, "Message was not deleted from queue after ack()"
