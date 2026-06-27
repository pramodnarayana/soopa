from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pipeline.adapters.storage import S3StorageAdapter

pytestmark = pytest.mark.asyncio


@patch("pipeline.adapters.storage.aioboto3.Session")
async def test_s3_storage_adapter_download(mock_session_cls: MagicMock) -> None:
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    mock_client = AsyncMock()
    mock_session.client.return_value.__aenter__.return_value = mock_client

    # Mock S3 response
    mock_body = AsyncMock()
    mock_body.read.return_value = b"test payload"
    mock_client.get_object.return_value = {"Body": mock_body}

    adapter = S3StorageAdapter(bucket_name="test-bucket", endpoint_url="http://localhost:4566")

    # Act
    result = await adapter.download("s3://test-bucket/path/to/file.txt")

    # Assert
    assert result == b"test payload"
    mock_session.client.assert_called_once_with(
        "s3", region_name="us-east-1", endpoint_url="http://localhost:4566"
    )
    mock_client.get_object.assert_awaited_once_with(Bucket="test-bucket", Key="path/to/file.txt")


@patch("pipeline.adapters.storage.aioboto3.Session")
async def test_s3_storage_adapter_upload(mock_session_cls: MagicMock) -> None:
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    mock_client = AsyncMock()
    mock_session.client.return_value.__aenter__.return_value = mock_client

    adapter = S3StorageAdapter(bucket_name="test-bucket")

    # Act
    uri = await adapter.upload(b"test data", key_prefix="/api_payloads/123", file_name="out.json")

    # Assert
    assert uri == "s3://test-bucket/api_payloads/123/out.json"
    mock_session.client.assert_called_once_with("s3", region_name="us-east-1")
    mock_client.put_object.assert_awaited_once_with(
        Bucket="test-bucket", Key="api_payloads/123/out.json", Body=b"test data"
    )
