import asyncio

import pytest
from botocore.exceptions import ClientError
from secret_store.adapters.aws_secrets_manager import AwsSecretsManagerAdapter

pytestmark = pytest.mark.integration

RETRIEVAL_TIMEOUT_SECONDS = 5.0
RETRIEVAL_RETRY_INTERVAL_SECONDS = 0.1
RESOURCE_NOT_FOUND_ERROR_CODE = "ResourceNotFoundException"


async def retrieve_secret_with_retry(adapter: AwsSecretsManagerAdapter, ref: str) -> bytes:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + RETRIEVAL_TIMEOUT_SECONDS

    while True:
        try:
            return await adapter.retrieve_secret(ref)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != RESOURCE_NOT_FOUND_ERROR_CODE:
                raise
            if loop.time() >= deadline:
                raise
            await asyncio.sleep(min(RETRIEVAL_RETRY_INTERVAL_SECONDS, deadline - loop.time()))


@pytest.fixture
def temp_secrets_dir(tmp_path):
    # Use a temporary directory for local sidecar fallback testing
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    return str(secrets_dir)


@pytest.mark.asyncio
async def test_aws_secrets_manager_integration(temp_secrets_dir):
    adapter = AwsSecretsManagerAdapter(secrets_mount_path=temp_secrets_dir)

    # Test storing a secret
    test_key_data = b"INTEGRATION_TEST_KEY_DATA"
    category = "test_category"

    ref = await adapter.store_private_key(test_key_data, category=category)
    assert ref.startswith(f"edi/{category}/")

    # Test retrieving the secret (should hit cache first if we were caching, but this is a fresh call or cache miss/hit)
    retrieved_data = await retrieve_secret_with_retry(adapter, ref)
    assert retrieved_data == test_key_data

    # Test deleting the secret
    await adapter.delete_secret(ref)

    # Verify it's deleted (cache cleared and AWS throws error)
    with pytest.raises(ClientError) as exc_info:
        await adapter.retrieve_secret(ref)
    assert exc_info.value.response["Error"]["Code"] == RESOURCE_NOT_FOUND_ERROR_CODE
