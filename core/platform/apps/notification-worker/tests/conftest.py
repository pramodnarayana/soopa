import asyncio
import os

os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

import pytest
import pytest_asyncio
from database.models.core import GlobalRegistry
from database.provider import get_async_engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_container(request):
    """Spin up a real Postgres database for the test session."""
    postgres = PostgresContainer("postgres:15-alpine")
    postgres.start()
    request.addfinalizer(postgres.stop)
    return postgres


@pytest_asyncio.fixture(scope="function")
async def db_engine(postgres_container):
    db_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    engine = get_async_engine(db_url)

    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS identity"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS notifications"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS observability"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS ucp"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS edi"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS scheduling"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS platform"))

        await conn.run_sync(GlobalRegistry.metadata.drop_all)
        await conn.run_sync(GlobalRegistry.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session_factory(db_engine):
    """
    Provide an async_sessionmaker bound to the engine.
    Every test function gets a fresh DB because db_engine drops and recreates schema.
    """
    SessionLocal = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)
    return SessionLocal
