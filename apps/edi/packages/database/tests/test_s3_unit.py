from unittest.mock import AsyncMock, patch

import pytest
from database.s3 import Aioboto3PayloadStorage


@pytest.fixture
def storage() -> Aioboto3PayloadStorage:
    return Aioboto3PayloadStorage(
        bucket="test-bucket",
        region="us-east-1",
        endpoint_url="http://localhost:4566",
        access_key_id="test_key",
        secret_access_key="test_secret",
    )


@pytest.mark.asyncio
async def test_aioboto3_payload_storage_upload(storage: Aioboto3PayloadStorage) -> None:
    mock_s3 = AsyncMock()

    # We patch the context manager returned by session.client
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_s3

    with patch.object(storage.session, "client", return_value=mock_cm):
        result = await storage.upload(tenant_id=1, message_id="msg-123", payload=b"payload_data")

    assert result == "s3://test-bucket/tenants/1/inbound/msg-123.bin"
    mock_s3.put_object.assert_called_once_with(
        Bucket="test-bucket",
        Key="tenants/1/inbound/msg-123.bin",
        Body=b"payload_data",
    )


@pytest.mark.asyncio
async def test_aioboto3_payload_storage_download_valid(storage: Aioboto3PayloadStorage) -> None:
    mock_s3 = AsyncMock()
    mock_stream = AsyncMock()
    mock_stream.read.return_value = b"downloaded_data"

    mock_response = {"Body": mock_stream}
    # Mock the __aenter__ for the stream context manager
    mock_stream.__aenter__.return_value = mock_stream

    mock_s3.get_object.return_value = mock_response

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_s3

    with patch.object(storage.session, "client", return_value=mock_cm):
        result = await storage.download("s3://test-bucket/tenants/1/inbound/msg-123.bin")

    assert result == b"downloaded_data"
    mock_s3.get_object.assert_called_once_with(
        Bucket="test-bucket", Key="tenants/1/inbound/msg-123.bin"
    )


@pytest.mark.asyncio
async def test_aioboto3_payload_storage_download_invalid_uri(
    storage: Aioboto3PayloadStorage,
) -> None:
    result = await storage.download("s3://wrong-bucket/some/key.bin")
    assert result is None


@pytest.mark.asyncio
async def test_aioboto3_payload_storage_generate_presigned_url(
    storage: Aioboto3PayloadStorage,
) -> None:
    mock_s3 = AsyncMock()
    mock_s3.generate_presigned_url.return_value = "https://presigned.url"

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_s3

    with patch.object(storage.session, "client", return_value=mock_cm):
        result = await storage.generate_presigned_url(
            "s3://test-bucket/key.bin",
            response_headers={"Content-Disposition": "attachment; filename=key.bin"},
        )

    assert result == "https://presigned.url"
    mock_s3.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={
            "Bucket": "test-bucket",
            "Key": "key.bin",
            "ResponseContentDisposition": "attachment; filename=key.bin",
        },
        ExpiresIn=3600,
    )


@pytest.mark.asyncio
async def test_aioboto3_payload_storage_generate_presigned_url_invalid_uri(
    storage: Aioboto3PayloadStorage,
) -> None:
    with pytest.raises(ValueError, match="does not belong to bucket"):
        await storage.generate_presigned_url("s3://wrong-bucket/key.bin")
