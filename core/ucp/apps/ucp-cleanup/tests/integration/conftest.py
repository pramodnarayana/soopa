import os
from collections.abc import AsyncGenerator

import pytest
from database.provider import DatabaseProvider, get_async_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def session_factory() -> "AsyncGenerator[async_sessionmaker[AsyncSession], None]":
    """
    Enterprise Integration Testing: Binds the session factory to a single
    outer transaction that is rolled back after every test.
    """
    database_url = os.environ["DATABASE_URL"]
    engine = get_async_engine(database_url)

    connection = await engine.connect()
    transaction = await connection.begin()

    # Bind the session to the connection so commits become nested SAVEPOINTs
    factory = async_sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    try:
        yield factory
    finally:
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
async def db_provider(session_factory: async_sessionmaker[AsyncSession]) -> DatabaseProvider:
    """
    Injects the safe, transactional session factory into the provider.
    """
    provider = DatabaseProvider()
    provider.session_factory = session_factory
    return provider
