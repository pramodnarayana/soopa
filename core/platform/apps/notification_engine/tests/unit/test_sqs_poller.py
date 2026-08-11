import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from notification_engine.adapters.inbound.sqs_poller import poll_sqs_queue


@pytest.mark.asyncio
async def test_poll_sqs_queue_success():
    processor_called = False

    async def fake_processor(body):
        nonlocal processor_called
        processor_called = True
        assert body == {"hello": "world"}

    # We will use an asyncio Event to break the while loop cleanly
    stop_event = asyncio.Event()

    with patch(
        "notification_engine.adapters.inbound.sqs_poller.aioboto3.Session"
    ) as mock_session_class:
        mock_session = mock_session_class.return_value

        mock_client = AsyncMock()
        mock_session.client.return_value.__aenter__.return_value = mock_client

        mock_client.get_queue_url.return_value = {"QueueUrl": "http://queue"}

        # We need receive_message to return a message, then wait/stop
        async def fake_receive(*args, **kwargs):
            if not processor_called:
                return {
                    "Messages": [
                        {"ReceiptHandle": "receipt_123", "Body": json.dumps({"hello": "world"})}
                    ]
                }
            else:
                stop_event.set()
                # Stop the test safely
                raise asyncio.CancelledError()

        mock_client.receive_message.side_effect = fake_receive

        try:
            task = asyncio.create_task(poll_sqs_queue("test_queue", fake_processor))
            await stop_event.wait()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        except asyncio.CancelledError:
            pass

        assert processor_called is True
        mock_client.delete_message.assert_called_once_with(
            QueueUrl="http://queue", ReceiptHandle="receipt_123"
        )


@pytest.mark.asyncio
async def test_poll_sqs_queue_invalid_json():
    # Test invalid json body to trigger delete
    stop_event = asyncio.Event()

    async def fake_processor(body):
        pass

    with patch(
        "notification_engine.adapters.inbound.sqs_poller.aioboto3.Session"
    ) as mock_session_class:
        mock_session = mock_session_class.return_value
        mock_client = AsyncMock()
        mock_session.client.return_value.__aenter__.return_value = mock_client
        mock_client.get_queue_url.return_value = {"QueueUrl": "http://queue"}

        call_count = 0

        async def fake_receive(*args, **kwargs):
            nonlocal call_count
            if call_count == 0:
                call_count += 1
                return {"Messages": [{"ReceiptHandle": "receipt_bad", "Body": "not-json"}]}
            else:
                stop_event.set()
                raise asyncio.CancelledError()

        mock_client.receive_message.side_effect = fake_receive

        try:
            task = asyncio.create_task(poll_sqs_queue("test_queue", fake_processor))
            await stop_event.wait()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        except asyncio.CancelledError:
            pass

        mock_client.delete_message.assert_called_once_with(
            QueueUrl="http://queue", ReceiptHandle="receipt_bad"
        )
