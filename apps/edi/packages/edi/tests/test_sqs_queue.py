from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from edi.adapters.outbound.messaging.sqs_queue import SQSMessageQueueAdapter

pytestmark = pytest.mark.asyncio


@patch("edi.adapters.outbound.messaging.sqs_queue.aioboto3.Session")
async def test_sqs_queue_adapter_send(mock_session_cls: MagicMock) -> None:
    # Setup mock aioboto3 session and client
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session

    mock_client = AsyncMock()
    mock_session.client.return_value.__aenter__.return_value = mock_client

    # Mock SQS responses
    mock_client.get_queue_url.return_value = {"QueueUrl": "https://sqs.aws.com/123/TranslateQueue"}

    # Act
    adapter = SQSMessageQueueAdapter(endpoint_url="http://localhost:4566")
    await adapter.send("TranslateQueue", {"trace_id": "123", "tenant_id": 99})

    # Assert
    mock_session.client.assert_called_once_with(
        "sqs", region_name="us-east-1", endpoint_url="http://localhost:4566"
    )
    mock_client.get_queue_url.assert_awaited_once_with(QueueName="TranslateQueue")
    mock_client.send_message.assert_awaited_once_with(
        QueueUrl="https://sqs.aws.com/123/TranslateQueue",
        MessageBody='{"trace_id": "123", "tenant_id": 99}',
    )
