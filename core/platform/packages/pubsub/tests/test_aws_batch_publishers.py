from unittest.mock import AsyncMock

import pytest
from database.events import EventEnvelope
from pubsub.aws.aws_sns_publisher import AwsSnsPublisher
from pubsub.aws.aws_sqs_publisher import AwsSqsPublisher


def _events(count: int) -> list[EventEnvelope]:
    return [
        EventEnvelope(
            id=f"event-{index}",
            source="test",
            event_type="test.event",
            tenant_id="tenant-1",
            idempotency_key=f"key-{index}",
            payload={"index": index},
        )
        for index in range(count)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("publisher", "method_name"),
    [
        (AwsSnsPublisher("topic.fifo"), "publish_batch"),
        (AwsSqsPublisher("queue.fifo"), "send_message_batch"),
    ],
)
async def test_fifo_batch_stops_after_failed_entry(publisher, method_name):
    client = AsyncMock()
    method = getattr(client, method_name)
    method.return_value = {
        "Successful": [{"Id": "0"}],
        "Failed": [{"Id": "1", "Code": "InternalError"}],
    }

    successful_ids = await publisher._publish_batch_internal(client, _events(11))

    assert successful_ids == ["event-0"]
    method.assert_awaited_once()


@pytest.mark.asyncio
async def test_standard_queue_continues_after_failed_chunk_entry():
    publisher = AwsSqsPublisher("queue")
    client = AsyncMock()
    client.send_message_batch.side_effect = [
        {"Successful": [], "Failed": [{"Id": "0", "Code": "InternalError"}]},
        {"Successful": [{"Id": "0"}], "Failed": []},
    ]

    successful_ids = await publisher._publish_batch_internal(client, _events(11))

    assert successful_ids == ["event-10"]
    assert client.send_message_batch.await_count == 2


@pytest.mark.asyncio
async def test_transport_failure_is_propagated_when_nothing_succeeds():
    publisher = AwsSnsPublisher("topic")
    client = AsyncMock()
    client.publish_batch.side_effect = RuntimeError("broker unavailable")

    with pytest.raises(RuntimeError, match="broker unavailable"):
        await publisher._publish_batch_internal(client, _events(11))

    assert client.publish_batch.await_count == 2
