import os
import socket
from collections.abc import AsyncGenerator

import pytest
from database.router import DatabaseRouter
from edi.adapters.outbound.security import network
from edi.adapters.outbound.security.network import validate_target_url


def test_validate_target_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # Enforce production mode to ensure SSRF validation is active
    monkeypatch.setenv("ENV", "production")

    public_host = "public.example"
    failed_host = "unresolvable.example"

    def resolve(host: object, port: object, *_args: object) -> list[tuple[object, ...]]:
        host_text = str(host)
        if host_text == failed_host:
            raise socket.gaierror
        address = "93.184.216.34" if host_text == public_host else host_text
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port or 0))]

    monkeypatch.setattr(network, "_orig_getaddrinfo", resolve)

    assert validate_target_url(f"http://{public_host}") is True
    assert validate_target_url("http://127.0.0.1") is False
    assert validate_target_url("ftp://example.com") is False
    assert validate_target_url("http://") is False
    assert validate_target_url("http://192.168.1.1") is False
    assert validate_target_url("http://10.0.0.1") is False

    assert validate_target_url(f"http://{failed_host}") is False


@pytest.fixture
async def router() -> "AsyncGenerator[DatabaseRouter, None]":
    global_db_url = os.environ["DATABASE_URL"]
    db_router = DatabaseRouter(global_db_url, pool_size=2, max_overflow=2)
    yield db_router
    await db_router.close_all()
