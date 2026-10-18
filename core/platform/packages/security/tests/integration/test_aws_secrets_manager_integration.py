"""Integration tests for AwsSecretsManagerAdapter against live LocalStack."""

import asyncio
from pathlib import Path

import pytest
from botocore.exceptions import ClientError
from security.adapters.secrets.aws_secrets_manager import AwsSecretsManagerAdapter

pytestmark = pytest.mark.integration

RETRIEVAL_TIMEOUT_SECONDS = 5.0
RETRIEVAL_RETRY_INTERVAL_SECONDS = 0.1


async def retrieve_secret_with_retry(adapter: AwsSecretsManagerAdapter, ref: str) -> bytes:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + RETRIEVAL_TIMEOUT_SECONDS

    while True:
        try:
            return await adapter.retrieve_secret(ref)
        except (ClientError, ValueError):
            if loop.time() >= deadline:
                raise
            await asyncio.sleep(min(RETRIEVAL_RETRY_INTERVAL_SECONDS, deadline - loop.time()))


@pytest.fixture
def temp_secrets_dir(tmp_path: Path) -> str:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    return str(secrets_dir)


@pytest.mark.asyncio
async def test_aws_secrets_manager_integration(temp_secrets_dir: str) -> None:
    adapter = AwsSecretsManagerAdapter(secrets_mount_path=temp_secrets_dir)

    # 1. Store secret in LocalStack Secrets Manager
    test_key_data = b"INTEGRATION_TEST_KEY_DATA"
    category = "test_category"

    ref = await adapter.store_private_key(test_key_data, category=category)
    assert ref.startswith(f"soopa/{category}/")

    # 2. Retrieve secret bytes
    retrieved_data = await retrieve_secret_with_retry(adapter, ref)
    assert retrieved_data == test_key_data

    # 3. Retrieve secret string
    secret_str = await adapter.get_secret(ref)
    assert secret_str == "INTEGRATION_TEST_KEY_DATA"

    # 4. Delete secret (both cache and LocalStack)
    await adapter.delete_secret(ref)

    # 5. Verify secret is no longer retrievable (fails fast with ValueError)
    with pytest.raises(ValueError, match="Secret not found"):
        await adapter.retrieve_secret(ref)
