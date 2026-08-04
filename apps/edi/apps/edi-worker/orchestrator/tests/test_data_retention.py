import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.core.scheduler.models import Job
from worker.jobs.data_retention import DataRetentionCleanupJobHandler


@pytest.mark.asyncio
async def test_data_retention_execute() -> None:
    db_router = MagicMock()
    mock_global_session = MagicMock()
    mock_global_session.execute = AsyncMock()

    mock_shard = MagicMock()
    mock_shard.name = "test_shard"
    mock_shard.dsn = "test_dsn"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_shard]
    mock_global_session.execute.return_value = mock_result

    async def get_global_session() -> "AsyncGenerator[Any, Any]":
        yield mock_global_session

    db_router.get_global_session = get_global_session

    handler = DataRetentionCleanupJobHandler(db_router)
    handler._cleanup_shard = AsyncMock(return_value=(15, 0))

    job = Job(id=uuid.uuid4(), name="data_retention_cleanup", payload={}, interval_seconds=120)

    next_run = await handler.execute(job)

    assert handler._cleanup_shard.await_count == 1
    handler._cleanup_shard.assert_awaited_with("test_shard", "test_dsn")

    assert next_run is None


@pytest.mark.asyncio
async def test_data_retention_execute_exception_propagates() -> None:
    db_router = MagicMock()
    mock_global_session = MagicMock()
    mock_global_session.execute = AsyncMock()

    mock_shard = MagicMock()
    mock_shard.name = "test_shard"
    mock_shard.dsn = "test_dsn"

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_shard]
    mock_global_session.execute.return_value = mock_result

    async def get_global_session() -> "AsyncGenerator[Any, Any]":
        yield mock_global_session

    db_router.get_global_session = get_global_session

    handler = DataRetentionCleanupJobHandler(db_router)
    handler._cleanup_shard = AsyncMock(side_effect=Exception("DB Down"))

    job = Job(id=uuid.uuid4(), name="data_retention_cleanup", payload={}, interval_seconds=120)

    with pytest.raises(Exception, match="DB Down"):
        await handler.execute(job)


@pytest.mark.asyncio
@patch("worker.jobs.data_retention.AsyncSession")
async def test_data_retention_cleanup_shard(mock_async_session: MagicMock) -> None:
    db_router = MagicMock()
    db_router.get_engine = AsyncMock(return_value=MagicMock())

    mock_session = MagicMock()
    mock_session.execute = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 42
    mock_session.execute.return_value = mock_result

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__.return_value = mock_session
    mock_session_ctx.__aexit__ = AsyncMock()

    mock_async_session.return_value = mock_session_ctx

    handler = DataRetentionCleanupJobHandler(db_router)

    processed = await handler._cleanup_shard("test_shard", "test_dsn")
    assert processed == (42, 42)
    assert mock_session.execute.await_count == 2
