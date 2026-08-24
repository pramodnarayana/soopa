import contextlib
import os

import aioboto3
import botocore.exceptions
import pytest

from edi.adapters.outbound.pipeline.storage import S3StorageClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock AWS Credentials for moto/localstack."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.mark.integration
async def test_s3_storage_adapter_integration(aws_credentials: None) -> None:
    """
    Narrow Integration Test for S3StorageClient.
    Connects to the LocalStack S3 container, creates a bucket,
    uploads a file, downloads it, and asserts the content matches.
    """
    endpoint_url = os.getenv("AWS_ENDPOINT_URL")
    if not endpoint_url:
        pytest.skip("AWS_ENDPOINT_URL is required for the LocalStack S3 integration test")
    bucket_name = "test-bucket-edi-pipeline"

    # Setup: Ensure bucket exists
    session = aioboto3.Session()
    async with session.client("s3", region_name="us-east-1", endpoint_url=endpoint_url) as s3:
        with contextlib.suppress(botocore.exceptions.ClientError):
            await s3.create_bucket(Bucket=bucket_name)

    # Initialize Adapter
    adapter = S3StorageClient(bucket_name=bucket_name, endpoint_url=endpoint_url)

    # Act: Upload
    test_data = b"real integration test payload for S3 storage pipeline"
    uri = await adapter.upload(test_data, key_prefix="/integration_test", file_name="test.txt")

    # Assert: Upload URI
    assert uri == f"s3://{bucket_name}/integration_test/test.txt"

    # Act: Download
    downloaded_data = await adapter.download(uri)

    # Assert: Download matches
    assert downloaded_data == test_data

    # Teardown: Clean up
    async with session.client("s3", region_name="us-east-1", endpoint_url=endpoint_url) as s3:
        await s3.delete_object(Bucket=bucket_name, Key="integration_test/test.txt")
