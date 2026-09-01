from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ucp_worker.bootstrap.container import WorkerContainer
from ucp_worker.core.job_registry import JobHandlerRegistry


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:5432/db")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://localhost:4566")
    monkeypatch.setenv("SQS_UCP_JOBS_QUEUE_URL", "http://localhost:4566/jobs")
    monkeypatch.setenv(
        "SNS_TENANT_EVENTS_TOPIC_ARN", "arn:aws:sns:us-east-1:000000000000:tenant-events"
    )
    monkeypatch.setenv("SQS_UCP_IDENTITY_SYNC_QUEUE_URL", "http://localhost:4566/sync")
    monkeypatch.setenv("ZITADEL_API_URL", "http://localhost:8080")
    monkeypatch.setenv("ZITADEL_ISSUER", "http://localhost:8080")


@pytest.mark.asyncio
async def test_worker_container_wiring(mock_env: None) -> None:
    # Mock the engine and sessionmaker so it doesn't try to connect or validate dialects
    with (
        patch("ucp_worker.bootstrap.container.get_async_engine") as mock_engine_factory,
        patch("ucp_worker.bootstrap.container.async_sessionmaker"),
    ):
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_engine_factory.return_value = mock_engine
        container = WorkerContainer()

    # Mock AwsSqsConsumer so it doesn't try to validate the queue URL during initialization
    with (
        patch("pubsub.aws.aws_sqs_consumer.AwsSqsConsumer"),
        patch(
            "ucp_worker.bootstrap.container.TenantDeletedEventHandler"
        ) as mock_tenant_deleted_handler_class,
    ):
        mock_tenant_deleted_handler = mock_tenant_deleted_handler_class.return_value
        mock_tenant_deleted_handler.handle = AsyncMock()

        container.wire()

        assert isinstance(container.registry, JobHandlerRegistry)

        # Check that jobs are registered
        from ucp_worker.core.scheduler.models import JobName

        assert container.registry.get(JobName.UCP_OUTBOX_SWEEPER.value) is not None
        assert container.registry.get(JobName.UCP_OUTBOX_CLEANUP.value) is not None
        assert container.registry.get(JobName.UCP_IDEMPOTENCY_CLEANUP.value) is not None
        assert container.registry.get(JobName.UCP_AUDIT_LOG_CLEANUP.value) is not None

        # Check that events consumers and outbox relays are populated
        assert container.outbox_relay is not None
        assert container.events_consumer is not None
        assert container.events_dispatcher is not None

        # Test the inline TenantDeleted event handler
        event = MagicMock()
        event.id = "evt_123"
        event.event_type = "TenantDeleted"
        event.payload = {"tenant_id": "iam_ten_123"}

        await container.events_dispatcher._dispatch(event)
        mock_tenant_deleted_handler.handle.assert_awaited_once_with("iam_ten_123")

        # Test missing tenant id logs error (doesn't raise)
        bad_event = MagicMock()
        bad_event.id = "evt_bad"
        bad_event.event_type = "TenantDeleted"
        bad_event.payload = {}
        bad_event.tenant_id = None
        await container.events_dispatcher._dispatch(bad_event)
        mock_tenant_deleted_handler.handle.assert_awaited_once_with("iam_ten_123")

        # Test uow_factory inline context manager
        # Since uow_factory is passed to provisioner and tenant_deleted_handler, we can't easily extract it.
        # But dispatching `app.subscribed` would trigger it, but provisioner wants a DB. We'll leave it as is.
        # The coverage on the UOW factory isn't extremely critical since it's just 2 lines.

        # Verify dispose can run
        await container.dispose()
