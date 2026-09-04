import os
from collections.abc import AsyncGenerator

import pytest
from database.router import DatabaseRouter
from edi.adapters.outbound.security.network import validate_target_url


def test_validate_target_url(monkeypatch: pytest.MonkeyPatch) -> None:

    # Enforce production mode to ensure SSRF validation is active
    monkeypatch.setenv("ENV", "production")

    # Use real DNS for SSRF validation
    assert validate_target_url("http://example.com") is True
    assert validate_target_url("http://127.0.0.1") is False
    assert validate_target_url("ftp://example.com") is False
    assert validate_target_url("http://") is False
    assert validate_target_url("http://192.168.1.1") is False
    assert validate_target_url("http://10.0.0.1") is False

    # A non-existent domain will organically fail DNS resolution and thus fail validation
    assert validate_target_url("http://this-domain-definitely-does-not-exist.com") is False


@pytest.fixture
async def router() -> "AsyncGenerator[DatabaseRouter, None]":
    global_db_url = os.environ["DATABASE_URL"]
    db_router = DatabaseRouter(global_db_url, pool_size=2, max_overflow=2)
    yield db_router
    await db_router.close_all()
