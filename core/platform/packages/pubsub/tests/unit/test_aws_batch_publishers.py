from unittest.mock import AsyncMock, MagicMock, patch

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


# ---------------------------------------------------------------------------
# Context Manager Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_manager_creates_and_destroys_client():
    publisher = AwsSnsPublisher("topic")
    mock_client = AsyncMock()
    mock_client_context = MagicMock()
    mock_client_context.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_context.__aexit__ = AsyncMock(return_value=False)
    publisher.session.client = MagicMock(return_value=mock_client_context)

    async with publisher as p:
        assert p._client is mock_client
        assert p._client_context is mock_client_context
    assert publisher._client is None
    assert publisher._client_context is None


# ---------------------------------------------------------------------------
# Destination Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_destination_raises_value_error():
    publisher = AwsSqsPublisher("")
    with pytest.raises(ValueError):
        await publisher.publish(_events(1)[0])
    with pytest.raises(ValueError):
        await publisher.publish_batch(_events(1))


# ---------------------------------------------------------------------------
# Publish Single
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_single_uses_shared_client_when_available():
    publisher = AwsSnsPublisher("topic")
    event = _events(1)[0]

    mock_client = AsyncMock()
    publisher._client = mock_client

    await publisher.publish(event)
    mock_client.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_single_creates_ephemeral_client_if_none():
    publisher = AwsSqsPublisher("queue")
    event = _events(1)[0]

    # We mock the session.client context manager
    mock_client = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_client

    with patch.object(publisher.session, "client", return_value=mock_cm):
        await publisher.publish(event)

    mock_client.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_single_logs_and_reraises_on_error():
    publisher = AwsSqsPublisher("queue")
    event = _events(1)[0]

    mock_client = AsyncMock()
    mock_client.send_message.side_effect = RuntimeError("Failed")
    publisher._client = mock_client

    with pytest.raises(RuntimeError):
        await publisher.publish(event)


# ---------------------------------------------------------------------------
# Publish Batch Outer Method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_batch_empty_list_returns_empty_immediately():
    publisher = AwsSnsPublisher("topic")
    result = await publisher.publish_batch([])
    assert result == []


@pytest.mark.asyncio
async def test_publish_batch_uses_shared_client_if_available():
    publisher = AwsSnsPublisher("topic")
    mock_client = AsyncMock()
    mock_client.publish_batch.return_value = {"Successful": [{"Id": "0"}], "Failed": []}
    publisher._client = mock_client

    result = await publisher.publish_batch(_events(1))
    assert result == ["event-0"]


@pytest.mark.asyncio
async def test_publish_batch_creates_ephemeral_client_if_none():
    publisher = AwsSnsPublisher("topic")
    mock_client = AsyncMock()
    mock_client.publish_batch.return_value = {"Successful": [{"Id": "0"}], "Failed": []}

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_client

    with patch.object(publisher.session, "client", return_value=mock_cm):
        result = await publisher.publish_batch(_events(1))

    assert result == ["event-0"]


@pytest.mark.asyncio
async def test_publish_batch_outer_method_reraises_on_error():
    publisher = AwsSnsPublisher("topic")
    mock_client = AsyncMock()
    mock_client.publish_batch.side_effect = RuntimeError("Failed batch")
    publisher._client = mock_client

    with pytest.raises(RuntimeError):
        await publisher.publish_batch(_events(1))


# ---------------------------------------------------------------------------
# publish_batch_internal FIFO break condition (line 132)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fifo_queue_breaks_on_transport_failure():
    publisher = AwsSqsPublisher("queue.fifo")
    client = AsyncMock()
    client.send_message_batch.side_effect = RuntimeError("Transport failure")

    with pytest.raises(RuntimeError):
        await publisher._publish_batch_internal(client, _events(11))

    # Should break after the first chunk (11 events = 2 chunks).
    # Since it's a transport failure and fifo, it breaks immediately.
    assert client.send_message_batch.await_count == 1
