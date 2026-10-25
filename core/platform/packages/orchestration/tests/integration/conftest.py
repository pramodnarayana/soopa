"""SAVEPOINT-isolated PostgreSQL test fixtures for the Durable Workflow Engine (`core/platform/packages/orchestration`)."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest_asyncio
from database.provider import get_async_engine
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from orchestration.adapters.outbound.database.models import WorkflowBase

load_dotenv()


def _get_workflow_test_db_url() -> str:
    return (
        os.environ.get("IP_DATABASE_URL")
        or os.environ.get("SHARD_OVERRIDES__IP_SHARD_1")
        or "postgresql+asyncpg://ip:ip_password@localhost:5434/ip_shard"
    )


@pytest_asyncio.fixture(scope="function")
async def workflow_db_engine() -> AsyncGenerator[AsyncEngine]:
    """Create an async SQLAlchemy engine and ensure WorkflowBase schema exists."""
    engine = get_async_engine(_get_workflow_test_db_url())
    async with engine.begin() as conn:
        await conn.run_sync(WorkflowBase.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def workflow_db_connection(
    workflow_db_engine: AsyncEngine,
) -> AsyncGenerator[AsyncConnection]:
    """Wrap each test in an outer transaction that rolls back completely upon completion."""
    connection = await workflow_db_engine.connect()
    transaction = await connection.begin()
    try:
        yield connection
    finally:
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture(scope="function")
async def workflow_session(
    workflow_db_connection: AsyncConnection,
) -> AsyncGenerator[AsyncSession]:
    """Provide a SAVEPOINT-isolated AsyncSession (`join_transaction_mode='create_savepoint'`)."""
    session_factory = async_sessionmaker(
        bind=workflow_db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )
    async with session_factory() as session:
        yield session
