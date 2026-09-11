import asyncio
import os

import pytest
import pytest_asyncio
from database.provider import DatabaseProvider
from dotenv import load_dotenv

load_dotenv()
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session_factory():
    """
    Provide an async_sessionmaker bound to a nested transaction (SAVEPOINT) for
    full test isolation. Rolls back all changes after each test — nothing is
    written to the physical database.
    """
    db_url = os.environ["DATABASE_URL"]
    provider = DatabaseProvider.from_url(db_url)

    connection = await provider.engine.connect()
    transaction = await connection.begin()

    session_factory = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )
    yield session_factory

    await transaction.rollback()
    await connection.close()
    await provider.close()
