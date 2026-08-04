from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.data.handlers import process_pipeline_event


@pytest.mark.asyncio
@patch("worker.data.handlers.SqlAlchemyRepositoryAdapter")
@patch("worker.data.handlers.BotsTransformerAdapter")
@patch("worker.data.handlers.S3StorageAdapter")
async def test_process_pipeline_event_idempotency_duplicate(mock_s3, mock_transformer, mock_repo):
    resolver = AsyncMock()
    resolver.resolve.return_value = ("shard_1", "fake_dsn")
    db_router = MagicMock()

    mock_session = AsyncMock()

    async def fake_get_tenant_session(*args, **kwargs):
        yield mock_session

    db_router.get_tenant_session.return_value = fake_get_tenant_session()

    # We need to mock session.execute returning None to simulate duplicate (nothing inserted)
    mock_existing = MagicMock()
    mock_existing.scalar_one_or_none.return_value = None  # simulating duplicate
    mock_session.execute.return_value = mock_existing

    await process_pipeline_event(
        trace_id="trace-123",
        event_type="INBOUND",
        payload={"direction": "INBOUND"},
        tenant_id=1,
        resolver=resolver,
        db_router=db_router,
        s3_bucket="test",
        aws_endpoint=None,
        idempotency_key="00000000-0000-0000-0000-000000000000",
    )
    # Verify it skips and returns early
    mock_session.commit.assert_called_once()
    mock_repo.assert_called_once()


@pytest.mark.asyncio
@patch("worker.data.handlers.SqlAlchemyRepositoryAdapter")
@patch("worker.data.handlers.S3StorageAdapter")
@patch("pipeline.core.saga.TraceLifecycleService")
async def test_process_pipeline_event_transform_completed(mock_trace, mock_s3, mock_repo):
    resolver = AsyncMock()
    resolver.resolve.return_value = ("shard_1", "fake_dsn")
    db_router = MagicMock()

    mock_session = AsyncMock()

    async def fake_get_tenant_session(*args, **kwargs):
        yield mock_session

    db_router.get_tenant_session.return_value = fake_get_tenant_session()

    # We mock it so it does not find a duplicate
    mock_inserted = MagicMock()
    mock_inserted.scalar_one_or_none.return_value = "fake-key"
    mock_session.execute.return_value = mock_inserted

    mock_saga = AsyncMock()
    mock_trace.return_value = mock_saga

    await process_pipeline_event(
        trace_id="trace-123",
        event_type="TRANSFORM_COMPLETED",
        payload={"direction": "INBOUND"},
        tenant_id=1,
        resolver=resolver,
        db_router=db_router,
        s3_bucket="test",
        aws_endpoint=None,
        idempotency_key="00000000-0000-0000-0000-000000000000",
    )
    mock_saga.handle_transform_completed.assert_called_once_with({"direction": "INBOUND"})


@pytest.mark.asyncio
@patch("worker.data.handlers.SqlAlchemyRepositoryAdapter")
@patch("worker.data.handlers.S3StorageAdapter")
@patch("pipeline.core.saga.TraceLifecycleService")
async def test_process_pipeline_event_delivery_completed(mock_trace, mock_s3, mock_repo):
    resolver = AsyncMock()
    resolver.resolve.return_value = ("shard_1", "fake_dsn")
    db_router = MagicMock()

    mock_session = AsyncMock()

    async def fake_get_tenant_session(*args, **kwargs):
        yield mock_session

    db_router.get_tenant_session.return_value = fake_get_tenant_session()

    # We mock it so it does not find a duplicate
    mock_inserted = MagicMock()
    mock_inserted.scalar_one_or_none.return_value = "fake-key"
    mock_session.execute.return_value = mock_inserted

    mock_saga = AsyncMock()
    mock_trace.return_value = mock_saga

    await process_pipeline_event(
        trace_id="trace-123",
        event_type="DELIVERY_COMPLETED",
        payload={"direction": "INBOUND"},
        tenant_id=1,
        resolver=resolver,
        db_router=db_router,
        s3_bucket="test",
        aws_endpoint=None,
        idempotency_key="00000000-0000-0000-0000-000000000000",
    )
    mock_saga.handle_delivery_completed.assert_called_once_with({"direction": "INBOUND"})


@pytest.mark.asyncio
@patch("worker.data.handlers.SqlAlchemyRepositoryAdapter")
@patch("worker.data.handlers.S3StorageAdapter")
@patch("worker.data.handlers.InboundTransformService")
async def test_process_pipeline_event_inbound(mock_inbound, mock_s3, mock_repo):
    resolver = AsyncMock()
    resolver.resolve.return_value = ("shard_1", "fake_dsn")
    db_router = MagicMock()

    mock_session = AsyncMock()

    async def fake_get_tenant_session(*args, **kwargs):
        yield mock_session

    db_router.get_tenant_session.return_value = fake_get_tenant_session()

    # We mock it so it does not find a duplicate
    mock_inserted = MagicMock()
    mock_inserted.scalar_one_or_none.return_value = "fake-key"
    mock_session.execute.return_value = mock_inserted

    mock_service = AsyncMock()
    mock_inbound.return_value = mock_service

    await process_pipeline_event(
        trace_id="trace-123",
        event_type="DOCUMENT_RECEIVED",
        payload={"direction": "INBOUND"},
        tenant_id=1,
        resolver=resolver,
        db_router=db_router,
        s3_bucket="test",
        aws_endpoint=None,
        idempotency_key="00000000-0000-0000-0000-000000000000",
    )
    mock_inbound.assert_called_once()
    mock_service.transform.assert_called_once_with("trace-123")


@pytest.mark.asyncio
@patch("worker.data.handlers.SqlAlchemyRepositoryAdapter")
@patch("worker.data.handlers.S3StorageAdapter")
@patch("worker.data.handlers.OutboundTransformService")
async def test_process_pipeline_event_outbound(mock_outbound, mock_s3, mock_repo):
    resolver = AsyncMock()
    resolver.resolve.return_value = ("shard_1", "fake_dsn")
    db_router = MagicMock()

    mock_session = AsyncMock()

    async def fake_get_tenant_session(*args, **kwargs):
        yield mock_session

    db_router.get_tenant_session.return_value = fake_get_tenant_session()

    # We mock it so it does not find a duplicate
    mock_inserted = MagicMock()
    mock_inserted.scalar_one_or_none.return_value = "fake-key"
    mock_session.execute.return_value = mock_inserted

    mock_service = AsyncMock()
    mock_outbound.return_value = mock_service

    await process_pipeline_event(
        trace_id="trace-123",
        event_type="OUTBOUND_REQUEST",
        payload={"direction": "OUTBOUND"},
        tenant_id=1,
        resolver=resolver,
        db_router=db_router,
        s3_bucket="test",
        aws_endpoint=None,
        idempotency_key="00000000-0000-0000-0000-000000000000",
    )
    mock_outbound.assert_called_once()
    mock_service.transform.assert_called_once_with("trace-123")


@pytest.mark.asyncio
@patch("worker.data.handlers.SqlAlchemyRepositoryAdapter")
@patch("worker.data.handlers.WebhookDeliveryStrategy")
@patch("worker.data.handlers.WorkerVaultAdapter")
async def test_process_delivery_success(mock_vault, mock_webhook, mock_repo):
    from worker.data.handlers import process_delivery

    resolver = AsyncMock()
    resolver.resolve.return_value = ("shard_1", "fake_dsn")
    db_router = MagicMock()

    mock_session = AsyncMock()

    async def fake_get_tenant_session(*args, **kwargs):
        yield mock_session

    db_router.get_tenant_session.side_effect = fake_get_tenant_session

    # Mock claiming the row
    mock_claimed = MagicMock()
    mock_claimed.scalar_one_or_none.return_value = "fake-key"
    mock_session.execute.return_value = mock_claimed
    mock_repo.return_value.get_edi_message = AsyncMock()
    mock_repo.return_value.update_edi_message = AsyncMock()
    mock_repo.return_value.get_route = AsyncMock()
    mock_repo.return_value.get_partnership = AsyncMock()
    mock_repo.return_value.get_edi_message.return_value = MagicMock(partner_id="p1", route_id="r1")
    mock_repo.return_value.get_route.return_value = MagicMock(webhook_id="w1")

    strategy_instance = AsyncMock()
    strategy_instance.deliver.return_value = True
    mock_webhook.return_value = strategy_instance

    await process_delivery(
        trace_id="trace-123",
        event_type="DELIVER_WEBHOOK",
        payload={"webhook_url": "http://test", "payload": {}},
        tenant_id=1,
        resolver=resolver,
        db_router=db_router,
        s3_bucket="test",
        aws_endpoint=None,
        idempotency_key="00000000-0000-0000-0000-000000000000",
    )

    mock_session.commit.assert_called()
    assert mock_session.execute.call_count >= 2


@pytest.mark.asyncio
@patch("worker.data.handlers.SqlAlchemyRepositoryAdapter")
@patch("worker.data.handlers.WebhookDeliveryStrategy")
@patch("worker.data.handlers.WorkerVaultAdapter")
async def test_process_delivery_skip(mock_vault, mock_webhook, mock_repo):
    from worker.data.handlers import process_delivery

    resolver = AsyncMock()
    resolver.resolve.return_value = ("shard_1", "fake_dsn")
    db_router = MagicMock()

    mock_session = AsyncMock()

    async def fake_get_tenant_session(*args, **kwargs):
        yield mock_session

    db_router.get_tenant_session.side_effect = fake_get_tenant_session

    # Mock skipping the row
    mock_skipped = MagicMock()
    mock_skipped.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_skipped

    await process_delivery(
        trace_id="trace-123",
        event_type="DELIVER_WEBHOOK",
        payload={"webhook_url": "http://test", "payload": {}},
        tenant_id=1,
        resolver=resolver,
        db_router=db_router,
        s3_bucket="test",
        aws_endpoint=None,
        idempotency_key="00000000-0000-0000-0000-000000000000",
    )

    # Only the claim query executed, delivery strategy not called
    mock_webhook.assert_not_called()
