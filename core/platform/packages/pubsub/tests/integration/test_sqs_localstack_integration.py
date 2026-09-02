import asyncio
import os
from collections.abc import AsyncGenerator

import boto3
import pytest
from database.events import EventEnvelope
from pubsub.aws.aws_sqs_consumer import AwsSqsConsumer
from pubsub.aws.aws_sqs_publisher import AwsSqsPublisher
from pubsub.message import AckableMessage
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
        aws_secret_access_key="test",  # noqa: S106
    )

    queue_name = f"pubsub-test-queue-{generate_random_hex(6)}"

    queue = sqs_client.create_queue(
        QueueName=queue_name,
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
@pytest.mark.integration
async def test_sqs_pubsub_integration_via_localstack(
    localstack_sqs: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    queue_url = localstack_sqs["sqs_queue_url"]
    endpoint_url = localstack_sqs["endpoint_url"]

    # Configure boto3 environment for aioboto3 used internally by the adapters
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    publisher = AwsSqsPublisher(
        queue_url=queue_url,
        region_name="us-east-1",
        endpoint_url=endpoint_url,
    )

    consumer = AwsSqsConsumer(
        queue_url=queue_url,
        region_name="us-east-1",
        endpoint_url=endpoint_url,
    )

    # 1. Publish a message
    test_event_id = f"evt_{generate_random_hex(6)}"
    test_event = EventEnvelope(
        id=test_event_id,
        source="integration_test",
        event_type="TEST_INTEGRATION_EVENT",
        tenant_id=None,
        idempotency_key=None,
        payload={"some_key": "some_value"},
    )

    await publisher.publish(test_event)

    # 2. Consume the message
    received_message: AckableMessage | None = None
    async with consumer as c:
        # Give LocalStack a tiny bit of time to make the message visible
        await asyncio.sleep(0.5)

        async with c.poll_raw_message() as msg:
            received_message = msg
            if msg is not None:
                await msg.ack()

    # 3. Assertions
    assert received_message is not None, "Consumer failed to poll the message from LocalStack"
    assert received_message.payload["id"] == test_event_id
    assert received_message.payload["event_type"] == "TEST_INTEGRATION_EVENT"
    assert received_message.payload["payload"]["some_key"] == "some_value"

    # 4. Verify message was deleted from the queue (ack worked)
    sqs_client = boto3.client(
        "sqs",
        endpoint_url=endpoint_url,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",  # noqa: S106
    )

    response = sqs_client.receive_message(
        QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=1
    )
    messages = response.get("Messages", [])
    assert len(messages) == 0, "Message was not deleted from queue after ack()"
