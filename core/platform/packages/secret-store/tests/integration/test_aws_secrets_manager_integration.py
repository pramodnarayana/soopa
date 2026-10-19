"""Integration tests for AwsSecretsManagerAdapter against live LocalStack."""

import asyncio
from pathlib import Path

import pytest
from botocore.exceptions import ClientError
from secret_store.adapters.aws_secrets_manager import AwsSecretsManagerAdapter
from secret_store.adapters.mounted_path_resolver import MountedSecretPathResolver

pytestmark = pytest.mark.integration

RETRIEVAL_TIMEOUT_SECONDS = 5.0
RETRIEVAL_RETRY_INTERVAL_SECONDS = 0.1


def _build_test_adapter(
    secrets_mount_path: str,
    path_resolver: MountedSecretPathResolver | None = None,
) -> AwsSecretsManagerAdapter:
    """Builds an adapter resolving endpoints and credentials via centralized PlatformAwsSettings."""
    return AwsSecretsManagerAdapter(
        secrets_prefix="",
        secrets_mount_path=secrets_mount_path,
        path_resolver=path_resolver,
    )


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
    adapter = _build_test_adapter(secrets_mount_path=temp_secrets_dir)

    # 1. Store secret in LocalStack Secrets Manager
    test_key_data = b"INTEGRATION_TEST_KEY_DATA"
    category = "test_category"

    ref = await adapter.store_private_key(test_key_data, category=category)
    assert ref.startswith(f"{category}/")

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


@pytest.mark.asyncio
async def test_aws_secrets_manager_integration_with_mounted_file(
    temp_secrets_dir: str,
) -> None:
    adapter = _build_test_adapter(
        secrets_mount_path=temp_secrets_dir,
        path_resolver=MountedSecretPathResolver(),
    )
    category = "sidecar_cat"
    test_data = b"INTEGRATION_SIDECAR_DATA"
    mounted_distinct_data = b"MOUNTED_DISTINCT_FILE_DATA"

    # 1. Store secret in LocalStack
    ref = await adapter.store_private_key(test_data, category=category)
    secret_id = ref.split("/")[-1]

    # 2. Simulate sidecar mounting file to {mount}/{category}/{id} (1:1 deterministic mapping)
    mounted_file = Path(temp_secrets_dir) / category / secret_id
    mounted_file.parent.mkdir(parents=True, exist_ok=True)
    mounted_file.write_bytes(mounted_distinct_data)

    assert mounted_file.is_file()

    # 3. Retrieve secret should hit the mounted file (returns mounted distinct bytes)
    retrieved = await adapter.retrieve_secret(ref)
    assert retrieved == mounted_distinct_data

    # 4. Delete secret should remove the local mounted file AND delete from LocalStack
    await adapter.delete_secret(ref)
    assert not mounted_file.exists()

    with pytest.raises(ValueError, match="Secret not found"):
        await adapter.retrieve_secret(ref)
