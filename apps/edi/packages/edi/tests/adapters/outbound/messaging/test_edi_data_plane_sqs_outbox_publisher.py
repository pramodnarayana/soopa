import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from database.events import EventEnvelope

from edi.adapters.outbound.messaging.edi_data_plane_sqs_outbox_publisher import (
    EdiDataPlaneSqsOutboxPublisherAdapter,
)

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
        "Successful": [{"Id": "0"}, {"Id": "1"}],
        "Failed": [{"Id": "2", "Message": "Error"}],
    }

    with patch("aioboto3.Session", return_value=mock_session):
        adapter = EdiDataPlaneSqsOutboxPublisherAdapter(region="us-east-1", endpoint_url=None)

        # Publish messages - event_type must match PIPELINE_EVENT_ROUTING_MAP
        # PIPELINE_EVENT_ROUTING_MAP has:
        # PipelineEventType.TRANSFORM_EVENT.value -> MessageQueueName.TRANSFORM_QUEUE.value
        messages = [
            EventEnvelope(
                id="111",
                event_type="pipeline.transform_requested",  # matching value in mapping
                payload={"event": "A"},
                idempotency_key="idem-1",
                source="test",
                tenant_id="tenant-1",
            ),
            EventEnvelope(
                id="222",
                event_type="pipeline.transform_requested",
                payload={"event": "B"},
                source="test",
                tenant_id="tenant-1",
                idempotency_key="idem-2",
            ),
            EventEnvelope(
                id="333",
                event_type="pipeline.transform_requested",
                payload={"event": "C"},
                source="test",
                tenant_id="tenant-1",
                idempotency_key="idem-3",
            ),
        ]

        # Patch the mapping for the test if necessary, but we can just use "pipeline.transform_requested"
        with patch(
            "edi.adapters.outbound.messaging.edi_data_plane_sqs_outbox_publisher.PIPELINE_EVENT_ROUTING_MAP",
            {"pipeline.transform_requested": "test-queue"},
        ):
            success_ids = await adapter.publish_batch(messages)

            assert success_ids == ["111", "222"]
            mock_client.get_queue_url.assert_called_once_with(QueueName="test-queue")
            mock_client.send_message_batch.assert_called_once()
            entries = mock_client.send_message_batch.await_args.kwargs["Entries"]

            assert json.loads(entries[0]["MessageBody"])["payload"] == {"event": "A"}
            assert (
                json.loads(entries[0]["MessageBody"])["event_type"]
                == "pipeline.transform_requested"
            )
            assert json.loads(entries[0]["MessageBody"])["idempotency_key"] == "idem-1"


async def test_sqs_publisher_publish_batch_unknown_event() -> None:
    mock_session = MagicMock()
    mock_client = AsyncMock()
    mock_session.client.return_value.__aenter__.return_value = mock_client

    with patch("aioboto3.Session", return_value=mock_session):
        adapter = EdiDataPlaneSqsOutboxPublisherAdapter(region="us-east-1", endpoint_url=None)

        messages = [
            EventEnvelope(
                id="111",
                event_type="unknown.event",
                payload={},
                source="test",
                tenant_id="tenant-1",
                idempotency_key="idem-1",
            ),
        ]

        success_ids = await adapter.publish_batch(messages)

        # It should just skip it and return empty
        assert success_ids == []
        mock_client.send_message_batch.assert_not_called()


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

        event = EventEnvelope(
            id="123",
            event_type="test.event",
            payload={"event": "A"},
            source="test",
            tenant_id="tenant-1",
            idempotency_key="idem-1",
        )

        with patch(
            "edi.adapters.outbound.messaging.edi_data_plane_sqs_outbox_publisher.PIPELINE_EVENT_ROUTING_MAP",
            {"test.event": "test-queue"},
        ):
            await adapter.publish(event)

            # Verify get_queue_url and send_message were called
            mock_client.get_queue_url.assert_called_once_with(QueueName="test-queue")
            mock_client.send_message.assert_called_once()

            # Call again to verify cache is used (get_queue_url should not be called again)
            event2 = EventEnvelope(
                id="124",
                event_type="test.event",
                payload={"event": "B"},
                source="test",
                tenant_id="tenant-1",
                idempotency_key="idem-2",
            )
            await adapter.publish(event2)
            assert mock_client.get_queue_url.call_count == 1
            assert mock_client.send_message.call_count == 2
