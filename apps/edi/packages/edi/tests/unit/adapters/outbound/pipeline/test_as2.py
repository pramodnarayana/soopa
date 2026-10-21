from functools import partial

import pytest
from pytest_httpserver import HTTPServer
from shttp import HttpClient

from edi.adapters.outbound.pipeline.as2 import HttpxAS2DeliveryClient
from edi.adapters.outbound.security.network import validate_target_url

pytestmark = pytest.mark.asyncio


async def test_as2_delivery_blocks_private_ip_by_default(httpserver: HTTPServer) -> None:
    client = HttpxAS2DeliveryClient()

    with pytest.raises(ValueError, match="SSRF validation failed"):
        await client.deliver(httpserver.url_for("/as2"), b"payload", {})


async def test_as2_delivery_allows_private_ip_when_enabled(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/as2", method="POST").respond_with_data("accepted", status=200)
    client = HttpxAS2DeliveryClient(
        validator=partial(validate_target_url, allow_private_ips=True),
        allow_private_ips=True,
    )

    status, _headers, body = await client.deliver(
        httpserver.url_for("/as2"),
        b"payload",
        {"Content-Type": "application/edi-x12"},
    )

    assert status == 200
    assert body == b"accepted"


async def test_as2_delivery_adapter_ownership_and_zero_retries() -> None:
    # 1. Owned client has zero retries configured
    client = HttpxAS2DeliveryClient()
    assert client._owned_client is True
    assert client._client._backoff_handler.max_retries == 0
    await client.close()
    assert client._client._client.is_closed

    # 2. Injected client is not closed by adapter
    shared_client = HttpClient(allow_private_ips=True)
    client2 = HttpxAS2DeliveryClient(client=shared_client)
    assert client2._owned_client is False
    await client2.close()
    assert not shared_client._client.is_closed
    await shared_client.close()
