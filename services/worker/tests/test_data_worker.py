import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from worker.data.main import poll_sqs_queue, process_delivery, process_translation

pytestmark = pytest.mark.asyncio


@patch("worker.data.main.aioboto3.Session")
async def test_poll_sqs_queue_processes_message(mock_session_cls: MagicMock) -> None:
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    mock_client = AsyncMock()
    mock_session.client.return_value.__aenter__.return_value = mock_client

    mock_client.get_queue_url.return_value = {"QueueUrl": "https://fake/queue"}

    mock_client.receive_message.side_effect = [
        {
            "Messages": [
                {
                    "ReceiptHandle": "receipt-123",
                    "Body": json.dumps({"tenant_id": 99, "payload": {"trace_id": "trace-456"}}),
                }
            ]
        },
        asyncio.CancelledError(),
    ]

    mock_processor = AsyncMock()
    mock_resolver = MagicMock()
    mock_db_router = MagicMock()

    with pytest.raises(asyncio.CancelledError):
        await poll_sqs_queue(
            "TranslateQueue",
            mock_processor,
            mock_resolver,
            mock_db_router,
            "bucket",
            "http://localhost",
        )

    mock_processor.assert_awaited_once_with(
        trace_id="trace-456",
        tenant_id=99,
        resolver=mock_resolver,
        db_router=mock_db_router,
        s3_bucket="bucket",
        aws_endpoint="http://localhost",
    )

    mock_client.delete_message.assert_awaited_once_with(
        QueueUrl="https://fake/queue", ReceiptHandle="receipt-123"
    )


@patch("worker.data.main.TranslationService")
async def test_process_translation(mock_service_cls: MagicMock) -> None:
    mock_service = AsyncMock()
    mock_service_cls.return_value = mock_service

    mock_resolver = AsyncMock()
    mock_resolver.resolve.return_value = ("shard1", "url")

    mock_db_router = MagicMock()
    mock_tenant_gen = AsyncMock()
    mock_tenant_session = AsyncMock()
    mock_db_router.get_tenant_session.return_value = mock_tenant_gen
    mock_tenant_gen.__anext__.return_value = mock_tenant_session

    await process_translation(
        "trace-123", 99, mock_resolver, mock_db_router, "bucket", "http://localhost"
    )

    mock_service.translate.assert_awaited_once_with("trace-123")


@patch("worker.data.main.DeliveryService")
async def test_process_delivery(mock_service_cls: MagicMock) -> None:
    mock_service = AsyncMock()
    mock_service_cls.return_value = mock_service

    mock_resolver = AsyncMock()
    mock_resolver.resolve.return_value = ("shard1", "url")

    mock_db_router = MagicMock()
    mock_tenant_gen = AsyncMock()
    mock_tenant_session = AsyncMock()
    mock_db_router.get_tenant_session.return_value = mock_tenant_gen
    mock_tenant_gen.__anext__.return_value = mock_tenant_session

    await process_delivery(
        "trace-123",
        "https://target.com",
        99,
        mock_resolver,
        mock_db_router,
        "bucket",
        "http://localhost",
    )

    mock_service.deliver.assert_awaited_once_with("trace-123", "https://target.com")
