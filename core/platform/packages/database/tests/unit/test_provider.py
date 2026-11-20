import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from database.exceptions import DatabaseConfigurationError
from database.provider import DatabaseProvider, get_async_engine


def test_get_async_engine():
    # Calling get_async_engine creates an AsyncEngine
    # We pass a simple valid sqlite or postgres memory url to ensure it builds correctly.
    # We don't want to actually connect, we just want to test creation.
    engine = get_async_engine("postgresql://user:pass@localhost:5432/db", pool_size=1)

    assert isinstance(engine, AsyncEngine)
    assert engine.url.drivername == "postgresql+asyncpg"


def test_get_async_engine_raises_on_empty_url():
    with pytest.raises(DatabaseConfigurationError) as exc_info:
        get_async_engine("")
    assert "empty or unconfigured" in str(exc_info.value)


def test_get_async_engine_raises_on_whitespace_url():
    with pytest.raises(DatabaseConfigurationError) as exc_info:
        get_async_engine("   ")
    assert "empty or unconfigured" in str(exc_info.value)


def test_from_url_raises_on_empty_url():
    with pytest.raises(DatabaseConfigurationError) as exc_info:
        DatabaseProvider.from_url("")
    assert "empty or unconfigured" in str(exc_info.value)
