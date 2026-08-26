import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from edi.adapters.outbound.messaging.edi_data_plane_sqs_outbox_publisher import (
    EdiDataPlaneSqsOutboxPublisherAdapter,
)
from edi.ports.outbound.edi_data_plane_outbox_publisher_port import PublishMessageEnvelope

pytestmark = pytest.mark.asyncio


async def test_sqs_publisher_publish_batch() -> None:
    mock_session = MagicMock()
    mock_client = AsyncMock()
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__.return_value = mock_client
    mock_client_ctx.__aexit__ = AsyncMock()
    mock_session.client.return_value = mock_client_ctx

    # Mock get_queue_url
    mock_client.get_queue_url.return_value = {"QueueUrl": "http://sqs/test"}
    # Mock send_message_batch
    mock_client.send_message_batch.return_value = {
        "Successful": [{"Id": "1"}, {"Id": "2"}],
        "Failed": [{"Id": "3", "Message": "Error"}],
    }

    with patch("aioboto3.Session", return_value=mock_session):
        adapter = EdiDataPlaneSqsOutboxPublisherAdapter(region="us-east-1", endpoint_url=None)

        async with adapter.connect():
            # Publish messages
            messages = [
                PublishMessageEnvelope(
                    message_id="1",
                    event_type="test",
                    event={"event": "A"},
                    idempotency_key="idem-1",
                ),
                PublishMessageEnvelope(message_id="2", event_type="test", event={"event": "B"}),
                PublishMessageEnvelope(message_id="3", event_type="test", event={"event": "C"}),
                PublishMessageEnvelope(
                    message_id="", event_type="test", event={"event": "MissingId"}
                ),
            ]

            success_ids = await adapter.publish_batch("test-queue", messages)

            assert success_ids == ["1", "2"]
            mock_client.get_queue_url.assert_called_once_with(QueueName="test-queue")
            mock_client.send_message_batch.assert_called_once()
            entries = mock_client.send_message_batch.await_args.kwargs["Entries"]
            assert json.loads(entries[0]["MessageBody"]) == {
                "event": "A",
                "event_type": "test",
                "idempotency_key": "idem-1",
            }


@pytest.mark.parametrize("reserved_key", ["event_type", "idempotency_key"])
async def test_sqs_publisher_rejects_reserved_event_keys(reserved_key: str) -> None:
    adapter = EdiDataPlaneSqsOutboxPublisherAdapter(region="us-east-1", endpoint_url=None)
    mock_client = AsyncMock()
    message = PublishMessageEnvelope(
        message_id="1",
        event_type="test",
        event={reserved_key: "payload-value"},
        idempotency_key="envelope-value",
    )

    with pytest.raises(ValueError, match=f"reserved envelope keys: {reserved_key}"):
        await adapter._send_batch_chunk("test-queue", "http://sqs/test", mock_client, [message])

    mock_client.send_message_batch.assert_not_awaited()


async def test_sqs_publisher_not_connected() -> None:
    adapter = EdiDataPlaneSqsOutboxPublisherAdapter(region="us-east-1", endpoint_url=None)
    with pytest.raises(RuntimeError, match="must be called within the connect"):
        await adapter.publish_batch(
            "test-queue", [PublishMessageEnvelope(message_id="1", event_type="test", event={})]
        )


async def test_sqs_publisher_get_queue_url_error() -> None:
    mock_session = MagicMock()
    mock_client = AsyncMock()
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__.return_value = mock_client
    mock_client_ctx.__aexit__ = AsyncMock()
    mock_session.client.return_value = mock_client_ctx

    mock_client.get_queue_url.side_effect = Exception("SQS Error")

    with patch("aioboto3.Session", return_value=mock_session):
        adapter = EdiDataPlaneSqsOutboxPublisherAdapter(region="us-east-1", endpoint_url=None)

        async with adapter.connect():
            success_ids = await adapter.publish_batch(
                "test-queue", [PublishMessageEnvelope(message_id="1", event_type="test", event={})]
            )
            assert success_ids == []


async def test_sqs_publisher_publish() -> None:
    mock_session = MagicMock()
    mock_client = AsyncMock()
    mock_client_ctx = MagicMock()
    mock_client_ctx.__aenter__.return_value = mock_client
    mock_client_ctx.__aexit__ = AsyncMock()
    mock_session.client.return_value = mock_client_ctx

    mock_client.get_queue_url.return_value = {"QueueUrl": "http://sqs/test"}

    with patch("aioboto3.Session", return_value=mock_session):
        adapter = EdiDataPlaneSqsOutboxPublisherAdapter(region="us-east-1", endpoint_url=None)
        await adapter.publish("test-queue", {"event": "A"})

        # Verify get_queue_url and send_message were called
        mock_client.get_queue_url.assert_called_once_with(QueueName="test-queue")
        mock_client.send_message.assert_called_once_with(
            QueueUrl="http://sqs/test", MessageBody='{"event": "A"}'
        )

        # Call again to verify cache is used (get_queue_url should not be called again)
        await adapter.publish("test-queue", {"event": "B"})
        assert mock_client.get_queue_url.call_count == 1
        assert mock_client.send_message.call_count == 2
