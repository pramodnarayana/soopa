from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from edi.adapters.outbound.httpx_as2_tester import HttpxAS2TesterAdapter


@pytest.fixture
def adapter():
    return HttpxAS2TesterAdapter()


@pytest.mark.asyncio
async def test_test_connection_success(adapter):
    with (
        patch("edi.adapters.outbound.httpx_as2_tester.build_outbound_message") as mock_build,
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("edi.adapters.outbound.httpx_as2_tester.parse_mdn") as mock_parse,
    ):
        mock_msg = MagicMock()
        mock_msg.body = b"mock_body"
        mock_msg.headers = {"Content-Type": "application/edi-x12"}
        mock_build.return_value = mock_msg

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"mdn content"
        mock_response.headers = httpx.Headers({"Content-Type": "multipart/report"})

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        # Async context manager mock
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client

        mock_mdn = MagicMock()
        mock_mdn.disposition = "processed"
        mock_parse.return_value = mock_mdn

        success, disposition, payload_str, full_mdn = await adapter.test_connection(
            remote_url="http://test.com",
            as2_from="ME",
            as2_to="YOU",
            local_private_key_pem=None,
            local_cert_pem=None,
            remote_cert_pem=None,
            encryption_algorithm="AES256",
            signature_algorithm="SHA256",
        )

        assert success is True
        assert disposition == "processed"
        assert payload_str is not None
        assert full_mdn is not None


@pytest.mark.asyncio
async def test_test_connection_build_fail(adapter):
    with patch("edi.adapters.outbound.httpx_as2_tester.build_outbound_message") as mock_build:
        mock_build.side_effect = ValueError("build error")

        success, reason, _payload, _mdn = await adapter.test_connection(
            remote_url="http://test.com",
            as2_from="ME",
            as2_to="YOU",
            local_private_key_pem=None,
            local_cert_pem=None,
            remote_cert_pem=None,
            encryption_algorithm="AES256",
            signature_algorithm="SHA256",
        )

        assert success is False
        assert "build error" in reason


@pytest.mark.asyncio
async def test_test_connection_http_fail(adapter):
    with (
        patch("edi.adapters.outbound.httpx_as2_tester.build_outbound_message") as mock_build,
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_build.return_value = MagicMock(body=b"", headers={})

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("refused")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client

        success, reason, _payload, _mdn = await adapter.test_connection(
            remote_url="http://test.com",
            as2_from="ME",
            as2_to="YOU",
            local_private_key_pem=None,
            local_cert_pem=None,
            remote_cert_pem=None,
            encryption_algorithm="AES256",
            signature_algorithm="SHA256",
        )

        assert success is False
        assert "refused" in reason


@pytest.mark.asyncio
async def test_test_connection_http_500(adapter):
    with (
        patch("edi.adapters.outbound.httpx_as2_tester.build_outbound_message") as mock_build,
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_build.return_value = MagicMock(body=b"", headers={})

        mock_response = MagicMock(status_code=500, content=b"", headers=httpx.Headers())
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client

        success, reason, _payload, _mdn = await adapter.test_connection(
            remote_url="http://test.com",
            as2_from="ME",
            as2_to="YOU",
            local_private_key_pem=None,
            local_cert_pem=None,
            remote_cert_pem=None,
            encryption_algorithm="AES256",
            signature_algorithm="SHA256",
        )

        assert success is False
        assert "HTTP 500" in reason


@pytest.mark.asyncio
async def test_test_connection_parse_fail(adapter):
    with (
        patch("edi.adapters.outbound.httpx_as2_tester.build_outbound_message") as mock_build,
        patch("httpx.AsyncClient") as mock_client_cls,
        patch("edi.adapters.outbound.httpx_as2_tester.parse_mdn") as mock_parse,
    ):
        mock_build.return_value = MagicMock(body=b"", headers={})

        mock_response = MagicMock(status_code=200, content=b"", headers=httpx.Headers())
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client

        mock_parse.side_effect = ValueError("parse fail")

        success, reason, _payload, _mdn = await adapter.test_connection(
            remote_url="http://test.com",
            as2_from="ME",
            as2_to="YOU",
            local_private_key_pem=None,
            local_cert_pem=None,
            remote_cert_pem=None,
            encryption_algorithm="AES256",
            signature_algorithm="SHA256",
        )

        assert success is False
        assert "parse fail" in reason


@pytest.mark.asyncio
async def test_test_connection_timeout(adapter):
    with (
        patch("edi.adapters.outbound.httpx_as2_tester.build_outbound_message") as mock_build,
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_build.return_value = MagicMock(body=b"", headers={})

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timeout")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client

        success, reason, _payload, _mdn = await adapter.test_connection(
            remote_url="http://test.com",
            as2_from="ME",
            as2_to="YOU",
            local_private_key_pem=None,
            local_cert_pem=None,
            remote_cert_pem=None,
            encryption_algorithm="AES256",
            signature_algorithm="SHA256",
        )

        assert success is False
        assert "timed out" in reason


@pytest.mark.asyncio
async def test_test_connection_generic_exception(adapter):
    with (
        patch("edi.adapters.outbound.httpx_as2_tester.build_outbound_message") as mock_build,
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_build.return_value = MagicMock(body=b"", headers={})

        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("generic error")
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client

        success, reason, _payload, _mdn = await adapter.test_connection(
            remote_url="http://test.com",
            as2_from="ME",
            as2_to="YOU",
            local_private_key_pem=None,
            local_cert_pem=None,
            remote_cert_pem=None,
            encryption_algorithm="AES256",
            signature_algorithm="SHA256",
        )

        assert success is False
        assert "HTTP error" in reason
