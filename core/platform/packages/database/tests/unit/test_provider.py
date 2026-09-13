from sqlalchemy.ext.asyncio import AsyncEngine

from database.provider import get_async_engine


def test_get_async_engine():
    # Calling get_async_engine creates an AsyncEngine
    # We pass a simple valid sqlite or postgres memory url to ensure it builds correctly.
    # We don't want to actually connect, we just want to test creation.
    engine = get_async_engine("postgresql://user:pass@localhost:5432/db", pool_size=1)

    assert isinstance(engine, AsyncEngine)
    assert engine.url.drivername == "postgresql+asyncpg"
