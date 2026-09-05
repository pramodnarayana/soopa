import os
import uuid

import aioboto3
import pytest

from edi.adapters.outbound.database.s3 import Aioboto3PayloadStorage


@pytest.fixture
async def storage() -> "aioboto3.Session":
    bucket_name = f"test-bucket-{uuid.uuid4().hex}"
    session = aioboto3.Session()
    async with session.client(
        "s3",
        region_name="us-east-1",
        endpoint_url="http://localhost:4566",
        aws_access_key_id="test",
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    ) as s3:
        await s3.create_bucket(Bucket=bucket_name)
        yield Aioboto3PayloadStorage(
            bucket=bucket_name,
            region="us-east-1",
            endpoint_url="http://localhost:4566",
            access_key_id="test",
            secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        )
        # Cleanup
        response = await s3.list_objects_v2(Bucket=bucket_name)
        if "Contents" in response:
            for obj in response["Contents"]:
                await s3.delete_object(Bucket=bucket_name, Key=obj["Key"])
        await s3.delete_bucket(Bucket=bucket_name)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_aioboto3_payload_storage_upload(storage: Aioboto3PayloadStorage) -> None:
    result = await storage.upload(tenant_id=1, message_id="msg-123", payload=b"payload_data")
    assert result == f"s3://{storage.bucket}/tenants/1/inbound/msg-123.bin"

    # verify
    data = await storage.download(result)
    assert data == b"payload_data"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_aioboto3_payload_storage_download_valid(storage: Aioboto3PayloadStorage) -> None:
    uri = await storage.upload(tenant_id=1, message_id="msg-123", payload=b"downloaded_data")
    result = await storage.download(uri)
    assert result == b"downloaded_data"


@pytest.mark.asyncio
async def test_aioboto3_payload_storage_download_invalid_uri(
    storage: Aioboto3PayloadStorage,
) -> None:
    result = await storage.download("s3://wrong-bucket/some/key.bin")
    assert result is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_aioboto3_payload_storage_generate_presigned_url(
    storage: Aioboto3PayloadStorage,
) -> None:
    # We upload so the key exists, though generate_presigned_url technically just signs locally
    uri = await storage.upload(tenant_id=1, message_id="key", payload=b"data")

    result = await storage.generate_presigned_url(
        uri,
        response_headers={"Content-Disposition": "attachment; filename=key.bin"},
    )

    assert result.startswith("http")
    assert "response-content-disposition=attachment" in result


@pytest.mark.asyncio
async def test_aioboto3_payload_storage_generate_presigned_url_invalid_uri(
    storage: Aioboto3PayloadStorage,
) -> None:
    with pytest.raises(ValueError, match="does not belong to bucket"):
        await storage.generate_presigned_url("s3://wrong-bucket/key.bin")
