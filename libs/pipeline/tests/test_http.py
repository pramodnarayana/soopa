from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pipeline.adapters.http import HttpxDeliveryAdapter

pytestmark = pytest.mark.asyncio


@patch("pipeline.adapters.http.httpx.AsyncClient")
async def test_httpx_delivery_adapter(mock_client_cls: MagicMock) -> None:
    mock_client = AsyncMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client.post.return_value = mock_response

    adapter = HttpxDeliveryAdapter(timeout_secs=5)

    status = await adapter.deliver("https://example.com/webhook", b'{"data": "test"}')

    assert status == 200
    mock_client.post.assert_awaited_once_with(
        "https://example.com/webhook",
        content=b'{"data": "test"}',
        headers={"Content-Type": "application/json"},
    )


def test_httpx_delivery_adapter_validator() -> None:
    def fail_validator(url: str) -> bool:
        return False

    adapter = HttpxDeliveryAdapter(timeout_secs=5, validator=fail_validator)

    with pytest.raises(ValueError, match="URL validation failed for provided destination."):
        import asyncio

        asyncio.run(adapter.deliver("https://bad.com", b"{}"))
