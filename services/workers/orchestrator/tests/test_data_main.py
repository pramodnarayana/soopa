import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from database.connection import DatabaseRouter
from worker.data.main import poll_sqs_queue, process_pipeline_event, validate_target_url

GLOBAL_DB_URL = os.getenv(
    "DB_GLOBAL_URL", "postgresql+asyncpg://edi:edi_password@localhost:5432/edi_global"
)
SHARD_1_URL = os.getenv(
    "DB_SHARD_1_URL", "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"
)


def test_validate_target_url():
    assert validate_target_url("http://example.com") is True
    assert validate_target_url("http://127.0.0.1") is False


@pytest.fixture
async def router():
    db_router = DatabaseRouter(GLOBAL_DB_URL, pool_size=2, max_overflow=2)
    yield db_router
    await db_router.close_all()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_pipeline_event_no_message(router: DatabaseRouter):
    # Setup TenantResolver double (since we don't want to seed global DB for this simple test)
    resolver = AsyncMock()
    resolver.resolve.return_value = ("shard_1", SHARD_1_URL)

    # Executing process_pipeline_event with a trace_id that doesn't exist
    # It will connect to the real test DB (shard_1), try to fetch the message, and fail.
    with pytest.raises(Exception, match=""):
        await process_pipeline_event(
            trace_id="nonexistent-trace-id",
            event_type="INBOUND",
            payload={"direction": "INBOUND"},
            tenant_id=999,
            resolver=resolver,
            db_router=router,
            s3_bucket="test-bucket",
            aws_endpoint=None,
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_process_delivery_no_message(router: DatabaseRouter):
    from worker.data.main import process_delivery

    resolver = AsyncMock()
    resolver.resolve.return_value = ("shard_1", SHARD_1_URL)

    with pytest.raises(Exception, match=""):
        await process_delivery(
            trace_id="nonexistent-trace-id",
            event_type="DELIVER",
            payload={},
            tenant_id=999,
            resolver=resolver,
            db_router=router,
            s3_bucket="test-bucket",
            aws_endpoint=None,
        )


@pytest.mark.asyncio
async def test_poll_sqs_queue():
    # Test the infrastructure polling loop.
    # We mock aioboto3 to return 1 message, then raise ValueError to break the infinite loop.
    mock_sqs = AsyncMock()
    mock_sqs.get_queue_url.return_value = {"QueueUrl": "http://queue"}

    # We yield one valid message, then one poison pill, then an exception to exit
    mock_sqs.receive_message.side_effect = [
        {
            "Messages": [
                {"ReceiptHandle": "1", "Body": '{"payload": {"trace_id": "123"}, "tenant_id": 999}'}
            ]
        },
        {"Messages": [{"ReceiptHandle": "2", "Body": "not json"}]},
        {"Messages": [{"ReceiptHandle": "3", "Body": '{"payload": {}, "tenant_id": null}'}]},
        ValueError("stop loop"),
    ]

    class MockClientContext:
        async def __aenter__(self):
            return mock_sqs

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_session = MagicMock()
    mock_session.client.return_value = MockClientContext()

    mock_processor = AsyncMock()

    with (
        patch("worker.data.main.aioboto3.Session", return_value=mock_session),
        patch("worker.data.main.asyncio.sleep", side_effect=Exception("Break out of retry loop")),
    ):
        try:
            await poll_sqs_queue(
                "test-queue",
                processor_func=mock_processor,
                resolver=AsyncMock(),
                db_router=AsyncMock(),
                s3_bucket="test-bucket",
                aws_endpoint=None,
            )
        except Exception as e:
            if str(e) != "Break out of retry loop":
                raise

    # Ensure processor was called for the valid message
    mock_processor.assert_called_once()
    assert mock_processor.call_args[1]["trace_id"] == "123"

    # Ensure all 3 messages were deleted (1 success, 2 poison)
    assert mock_sqs.delete_message.call_count == 3
