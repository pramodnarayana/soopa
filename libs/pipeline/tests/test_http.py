from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pipeline.adapters.http import HttpxDeliveryAdapter

pytestmark = pytest.mark.asyncio


@patch("pipeline.adapters.http.httpx.AsyncClient")
@patch("socket.getaddrinfo")
async def test_httpx_delivery_adapter(
    mock_getaddrinfo: MagicMock, mock_client_cls: MagicMock
) -> None:
    mock_client = AsyncMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client.post.return_value = mock_response

    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]

    adapter = HttpxDeliveryAdapter(timeout_secs=5)

    status = await adapter.deliver("https://example.com/webhook", b'{"data": "test"}')

    assert status == 200
    mock_client.post.assert_awaited_once_with(
        "https://93.184.216.34/webhook",
        content=b'{"data": "test"}',
        headers={"Content-Type": "application/json", "Host": "example.com"},
    )
