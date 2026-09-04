import os
import uuid

import aioboto3
import pytest

from edi.adapters.outbound.database.s3 import Aioboto3PayloadStorage

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def s3_bucket() -> str:
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
        yield bucket_name
        # Cleanup
        response = await s3.list_objects_v2(Bucket=bucket_name)
        if "Contents" in response:
            for obj in response["Contents"]:
                await s3.delete_object(Bucket=bucket_name, Key=obj["Key"])
        await s3.delete_bucket(Bucket=bucket_name)


@pytest.mark.integration
async def test_aioboto3_payload_storage_upload(s3_bucket: str) -> None:

    storage = Aioboto3PayloadStorage(
        bucket=s3_bucket,
        region="us-east-1",
        endpoint_url="http://localhost:4566",
        access_key_id="test",
        secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )

    uri = await storage.upload(tenant_id=1, message_id="msg123", payload=b"hello")

    assert uri == f"s3://{s3_bucket}/tenants/1/inbound/msg123.bin"

    # Verify by downloading it back using the storage interface
    downloaded = await storage.download(uri)
    assert downloaded == b"hello"


@pytest.mark.integration
async def test_aioboto3_payload_storage_download(s3_bucket: str) -> None:
    storage = Aioboto3PayloadStorage(
        bucket=s3_bucket,
        region="us-east-1",
        endpoint_url="http://localhost:4566",
        access_key_id="test",
        secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )

    # Upload first
    uri = await storage.upload(tenant_id=1, message_id="msg123", payload=b"downloaded_data")

    # Then download
    data = await storage.download(uri)

    assert data == b"downloaded_data"


async def test_aioboto3_payload_storage_download_invalid_uri() -> None:
    storage = Aioboto3PayloadStorage(bucket="test-bucket", region="us-east-1")
    data = await storage.download("s3://other-bucket/test")
    assert data is None
