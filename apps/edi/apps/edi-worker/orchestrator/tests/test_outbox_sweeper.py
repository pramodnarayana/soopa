import datetime
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.core.scheduler.models import Job
from worker.jobs.outbox_sweeper import DataPlaneOutboxSweeperJobHandler


@pytest.mark.asyncio
async def test_outbox_sweeper_execute():
    db_router = MagicMock()
    message_publisher = MagicMock()
    message_publisher.connect.return_value.__aenter__ = AsyncMock()
    message_publisher.connect.return_value.__aexit__ = AsyncMock()

    mock_global_session = MagicMock()
    mock_global_session.execute = AsyncMock()

    mock_shard = MagicMock()
    mock_shard.name = "test_shard"
    mock_shard.dsn = "test_dsn"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_shard]
    mock_global_session.execute.return_value = mock_result

    async def get_global_session():
        yield mock_global_session

    db_router.get_global_session = get_global_session

    handler = DataPlaneOutboxSweeperJobHandler(db_router, message_publisher)
    handler._sweep_shard = AsyncMock(return_value=5)

    job = Job(id=uuid.uuid4(), name="outbox_sweeper", payload={}, interval_seconds=120)

    next_run = await handler.execute(job)

    assert handler._sweep_shard.await_count == 1
    handler._sweep_shard.assert_awaited_with("test_shard", "test_dsn")

    assert next_run is not None
    assert isinstance(next_run, datetime.datetime)


@pytest.mark.asyncio
async def test_outbox_sweeper_execute_exception_caught():
    db_router = MagicMock()
    message_publisher = MagicMock()
    message_publisher.connect.return_value.__aenter__ = AsyncMock()
    message_publisher.connect.return_value.__aexit__ = AsyncMock()

    mock_global_session = MagicMock()
    mock_global_session.execute = AsyncMock()

    mock_shard = MagicMock()
    mock_shard.name = "test_shard"
    mock_shard.dsn = "test_dsn"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_shard]
    mock_global_session.execute.return_value = mock_result

    async def get_global_session():
        yield mock_global_session

    db_router.get_global_session = get_global_session

    handler = DataPlaneOutboxSweeperJobHandler(db_router, message_publisher)
    handler._sweep_shard = AsyncMock(side_effect=Exception("Database down"))

    job = Job(id=uuid.uuid4(), name="outbox_sweeper", payload={}, interval_seconds=120)

    next_run = await handler.execute(job)

    assert handler._sweep_shard.await_count == 1
    assert next_run is not None


@pytest.mark.asyncio
@patch("worker.jobs.outbox_sweeper.AsyncSession")
async def test_outbox_sweep_shard_no_events(mock_async_session):
    db_router = MagicMock()
    db_router.get_engine = AsyncMock(return_value=MagicMock())
    message_publisher = MagicMock()

    mock_session = MagicMock()
    mock_session.execute = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock()

    mock_async_session.return_value = mock_session_ctx

    handler = DataPlaneOutboxSweeperJobHandler(db_router, message_publisher)

    processed = await handler._sweep_shard("test_shard", "test_dsn")
    assert processed == 0


@pytest.mark.asyncio
@patch("worker.jobs.outbox_sweeper.AsyncSession")
async def test_outbox_sweep_shard_with_events(mock_async_session):
    db_router = MagicMock()
    db_router.get_engine = AsyncMock(return_value=MagicMock())
    message_publisher = MagicMock()
    message_publisher.publish_batch = AsyncMock(return_value=["1", "2"])

    mock_session = MagicMock()
    mock_session.execute = AsyncMock()

    mock_event1 = MagicMock()
    mock_event1.id = "1"
    mock_event1.event_type = "TRANSFORM_EVENT"
    mock_event1.payload = {"foo": "bar"}

    mock_event2 = MagicMock()
    mock_event2.id = "2"
    mock_event2.event_type = "DELIVER_EVENT"
    mock_event2.payload = {"baz": "qux"}

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_event1, mock_event2]
    mock_session.execute.return_value = mock_result

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock()

    mock_async_session.return_value = mock_session_ctx

    handler = DataPlaneOutboxSweeperJobHandler(db_router, message_publisher)

    processed = await handler._sweep_shard("test_shard", "test_dsn")
    assert processed == 2
    message_publisher.publish_batch.assert_awaited()
