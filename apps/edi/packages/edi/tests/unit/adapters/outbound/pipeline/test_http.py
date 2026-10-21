import pytest
from pytest_httpserver import HTTPServer
from shttp import HttpClient

from edi.adapters.outbound.pipeline.http import HttpxDeliveryClient

pytestmark = pytest.mark.asyncio


async def test_httpx_delivery_adapter(
    monkeypatch: pytest.MonkeyPatch, httpserver: HTTPServer
) -> None:

    httpserver.expect_request("/webhook", method="POST").respond_with_data(
        '{"success": true}', status=200
    )

    adapter = HttpxDeliveryClient(allow_private_ips=True)
    status, response_body = await adapter.deliver(
        httpserver.url_for("/webhook"), b'{"data": "test"}'
    )

    assert status == 200
    assert response_body == '{"success": true}'


async def test_httpx_delivery_adapter_validator() -> None:
    def fail_validator(url: str) -> bool:
        return False

    adapter = HttpxDeliveryClient(timeout_secs=5, validator=fail_validator, allow_private_ips=True)

    with pytest.raises(ValueError, match=r"URL validation failed for provided destination\."):
        await adapter.deliver("https://bad.com", b"{}")


async def test_httpx_delivery_adapter_ownership_and_close() -> None:
    adapter = HttpxDeliveryClient(allow_private_ips=True)
    assert adapter._owned_client is True
    assert adapter._client._backoff_handler.max_retries == 0
    await adapter.close()
    assert adapter._client._client.is_closed

    shared_client = HttpClient(allow_private_ips=True)
    adapter2 = HttpxDeliveryClient(client=shared_client)
    assert adapter2._owned_client is False
    await adapter2.close()
    assert not shared_client._client.is_closed
    await shared_client.close()
