"""Unit tests for HttpClient and factory."""

from __future__ import annotations

import httpx
import pytest
from shttp.client import HttpClient, create_http_client


def test_create_http_client() -> None:
    client = create_http_client()
    assert isinstance(client, httpx.AsyncClient)
    assert client.is_closed is False


@pytest.mark.asyncio
async def test_http_client_context_manager() -> None:
    async with HttpClient(allow_private_ips=True) as client:
        assert isinstance(client.raw_client, httpx.AsyncClient)
        assert client.raw_client.is_closed is False
    assert client.raw_client.is_closed is True
