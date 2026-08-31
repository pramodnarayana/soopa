import os
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.adapters.outbound.security.network import validate_target_url
from sqlalchemy.engine.url import make_url

raw_global_url = os.getenv(
    "DATABASE_URL", "postgresql://ucp_admin:ucp_password@localhost:5432/ucp_global"
)
parsed_global_url = make_url(raw_global_url).set(drivername="postgresql+asyncpg")
GLOBAL_DB_URL = os.getenv("DB_GLOBAL_URL", parsed_global_url.render_as_string(hide_password=False))

raw_shard_1_url = os.getenv(
    "SHARD_1_URL", "postgresql://edi:edi_password@localhost:5433/edi_shard_1"
)
parsed_shard_1_url = make_url(raw_shard_1_url).set(drivername="postgresql+asyncpg")
SHARD_1_URL = os.getenv("DB_SHARD_1_URL", parsed_shard_1_url.render_as_string(hide_password=False))


def test_validate_target_url(monkeypatch: MagicMock) -> None:
    import edi.adapters.outbound.security.network
    from edi.config.settings import AppSettings

    mock_settings = MagicMock(spec=AppSettings)
    mock_settings.env = "production"
    monkeypatch.setattr(
        edi.adapters.outbound.security.network, "get_settings", lambda: mock_settings
    )

    def mock_getaddrinfo(
        host: str, *args: Any, **kwargs: Any
    ) -> list[tuple[None, None, None, None, tuple[str, int]]]:
        if host == "example.com":
            return [(None, None, None, None, ("93.184.216.34", 80))]
        return [(None, None, None, None, (host, 80))]

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        assert validate_target_url("http://example.com") is True
        assert validate_target_url("http://127.0.0.1") is False
        assert validate_target_url("ftp://example.com") is False
        assert validate_target_url("http://") is False
        assert validate_target_url("http://192.168.1.1") is False
        assert validate_target_url("http://10.0.0.1") is False

    with patch("socket.getaddrinfo", side_effect=Exception("mock err")):
        assert validate_target_url("http://example.com") is False


@pytest.fixture
async def router() -> "AsyncGenerator[DatabaseRouter, None]":
    db_router = DatabaseRouter(GLOBAL_DB_URL, pool_size=2, max_overflow=2)
    yield db_router
    await db_router.close_all()
