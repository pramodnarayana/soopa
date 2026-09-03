import contextlib
from unittest.mock import MagicMock, patch

import pytest

from edi.adapters.outbound.pipeline.http import HttpxDeliveryClient

pytestmark = pytest.mark.asyncio


from pytest_httpserver import HTTPServer


@patch("edi.adapters.outbound.pipeline.http.ssrf_safe_context")
async def test_httpx_delivery_adapter(mock_ssrf: MagicMock, httpserver: HTTPServer) -> None:
    mock_ssrf.return_value = contextlib.nullcontext()

    httpserver.expect_request("/webhook", method="POST").respond_with_data(
        '{"success": true}', status=200
    )

    adapter = HttpxDeliveryClient()
    status, response_body = await adapter.deliver(
        httpserver.url_for("/webhook"), b'{"data": "test"}'
    )

    assert status == 200
    assert response_body == '{"success": true}'


async def test_httpx_delivery_adapter_validator() -> None:
    def fail_validator(url: str) -> bool:
        return False

    adapter = HttpxDeliveryClient(timeout_secs=5, validator=fail_validator)

    with pytest.raises(ValueError, match=r"URL validation failed for provided destination\."):
        await adapter.deliver("https://bad.com", b"{}")
