import asyncio

import pytest
from secret_store.adapters.aws_secrets_manager import AwsSecretsManagerAdapter

pytestmark = pytest.mark.integration


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

    # Give localstack a moment
    await asyncio.sleep(0.5)

    # Test retrieving the secret (should hit cache first if we were caching, but this is a fresh call or cache miss/hit)
    retrieved_data = await adapter.retrieve_secret(ref)
    assert retrieved_data == test_key_data

    # Test deleting the secret
    await adapter.delete_secret(ref)

    # Verify it's deleted (cache cleared and AWS throws error)
    with pytest.raises(Exception):  # noqa: B017
        await adapter.retrieve_secret(ref)
