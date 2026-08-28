import asyncio
import os

os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

import pytest
import pytest_asyncio
from database.provider import get_async_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    db_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
    )
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = get_async_engine(db_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session_factory(db_engine):
    """
    Provide an async_sessionmaker bound to a transaction for isolation.
    """
    connection = await db_engine.connect()
    transaction = await connection.begin()

    SessionLocal = async_sessionmaker(bind=connection, expire_on_commit=False, class_=AsyncSession)
    yield SessionLocal

    await transaction.rollback()
    await connection.close()
