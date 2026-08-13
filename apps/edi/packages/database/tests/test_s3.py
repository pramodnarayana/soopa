from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database.s3 import Aioboto3PayloadStorage

pytestmark = pytest.mark.asyncio


async def test_aioboto3_payload_storage_upload() -> None:
    with patch("database.s3.aioboto3.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_client = AsyncMock()
        # Mock the async context manager returned by session.client
        mock_client.__aenter__.return_value = mock_client
        mock_session.client.return_value = mock_client
        mock_session_cls.return_value = mock_session

        storage = Aioboto3PayloadStorage(
            bucket="test-bucket",
            region="us-east-1",
            endpoint_url="http://localhost:4566",
            access_key_id="test",
            # Safe: This is a dummy key for localstack S3 mocking, not a real AWS secret
            secret_access_key="test",  # noqa: S106
        )

        uri = await storage.upload(tenant_id=1, message_id="msg123", payload=b"hello")

        assert uri == "s3://test-bucket/tenants/1/inbound/msg123.bin"
        mock_client.put_object.assert_called_once_with(
            Bucket="test-bucket", Key="tenants/1/inbound/msg123.bin", Body=b"hello"
        )


async def test_aioboto3_payload_storage_download() -> None:
    with patch("database.s3.aioboto3.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_session.client.return_value = mock_client
        mock_session_cls.return_value = mock_session

        # Mock the response dict with a Body that is an async context manager
        mock_stream = AsyncMock()
        mock_stream.__aenter__.return_value = mock_stream
        mock_stream.read.return_value = b"downloaded_data"

        mock_client.get_object.return_value = {"Body": mock_stream}

        storage = Aioboto3PayloadStorage(bucket="test-bucket", region="us-east-1")

        data = await storage.download("s3://test-bucket/tenants/1/inbound/msg123.bin")

        assert data == b"downloaded_data"
        mock_client.get_object.assert_called_once_with(
            Bucket="test-bucket", Key="tenants/1/inbound/msg123.bin"
        )


async def test_aioboto3_payload_storage_download_invalid_uri() -> None:
    storage = Aioboto3PayloadStorage(bucket="test-bucket", region="us-east-1")
    data = await storage.download("s3://other-bucket/test")
    assert data is None
