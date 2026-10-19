from pathlib import Path

import pytest
from botocore.exceptions import ClientError
from secret_store.adapters.aws_secrets_manager import AwsSecretsManagerAdapter
from secret_store.adapters.mounted_path_resolver import MountedSecretPathResolver
from secret_store.provider import SecretStoreBackend, SecretStoreProvider
from secret_store.testing.fakes.in_memory_vault import InMemoryVaultAdapter


@pytest.mark.asyncio
async def test_in_memory_vault_lifecycle() -> None:
    vault = InMemoryVaultAdapter()

    key_bytes = b"-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----"
    ref = await vault.store_private_key(key_bytes, category="as2_partner")
    assert ref.startswith("as2_partner/")

    retrieved = await vault.retrieve_secret(ref)
    assert retrieved == key_bytes

    # Test get_secret and retrieve_private_key
    secret_str = await vault.get_secret(ref)
    assert secret_str == key_bytes.decode("utf-8")

    priv_key = await vault.retrieve_private_key(ref)
    assert priv_key == key_bytes

    await vault.delete_secret(ref)
    with pytest.raises(ValueError, match="Secret not found"):
        await vault.retrieve_secret(ref)


def test_mounted_secret_path_resolver_edge_cases(tmp_path: Path) -> None:
    resolver = MountedSecretPathResolver()
    assert resolver.resolve(tmp_path, "") is None
    assert resolver.resolve(tmp_path, "///") is None
    assert resolver.resolve(tmp_path, "invalid\x00path") is None


class FakeSecretsManagerClient:
    def __init__(self, responses: dict[str, Exception | dict[str, object]] | None = None) -> None:
        self.responses = responses or {}
        self.created_secrets: list[dict[str, str]] = []
        self.deleted_secrets: list[str] = []

    def create_secret(
        self, *, Name: str, SecretString: str, Description: str = ""
    ) -> dict[str, object]:
        self.created_secrets.append({"Name": Name, "SecretString": SecretString})
        return {"ARN": f"arn:aws:secretsmanager:::secret:{Name}", "Name": Name}

    def get_secret_value(self, *, SecretId: str) -> dict[str, object]:
        if SecretId in self.responses:
            val = self.responses[SecretId]
            if isinstance(val, Exception):
                raise val
            return val
        return {"SecretString": "mock_secret"}

    def delete_secret(self, *, SecretId: str, RecoveryWindowInDays: int = 7) -> dict[str, object]:
        if SecretId in self.responses and isinstance(self.responses[SecretId], Exception):
            raise self.responses[SecretId]
        self.deleted_secrets.append(SecretId)
        return {"ARN": f"arn:aws:secretsmanager:::secret:{SecretId}", "Name": SecretId}


@pytest.mark.asyncio
async def test_aws_secrets_manager_path_traversal_and_sidecar_cleanup(
    tmp_path: Path,
) -> None:
    mount_dir = tmp_path / "secrets_mount"
    mount_dir.mkdir()
    secret_file = mount_dir / "as2" / "test_key"
    secret_file.parent.mkdir(parents=True)
    secret_file.write_bytes(b"mounted_secret_content")

    fake_client = FakeSecretsManagerClient()
    adapter = AwsSecretsManagerAdapter(
        secrets_mount_path=str(mount_dir),
        client=fake_client,
        path_resolver=MountedSecretPathResolver(),
    )

    # Valid read from mounted directory using deterministic 1:1 mapping
    retrieved = await adapter.retrieve_secret("as2/test_key")
    assert retrieved == b"mounted_secret_content"

    # Direct resolution tests
    assert adapter._resolve_mounted_path("as2/test_key") == secret_file

    # Path traversal attack attempts should be rejected (returning None from resolution)
    assert adapter._resolve_mounted_path("../../etc/passwd") is None
    assert adapter._resolve_mounted_path("as2/../test_key") is not None
    assert adapter._resolve_mounted_path("as2/../../../etc/passwd") is None
    assert adapter._resolve_mounted_path("/etc/passwd") is not None
    resolved = adapter._resolve_mounted_path("../../../etc/shadow")
    assert resolved is None

    # Sidecar file cleanup on delete_secret
    assert secret_file.exists()
    await adapter.delete_secret("as2/test_key")
    assert not secret_file.exists()
    assert fake_client.deleted_secrets == ["as2/test_key"]


def test_aws_secrets_manager_without_path_resolver(tmp_path: Path) -> None:
    fake_client = FakeSecretsManagerClient()
    adapter = AwsSecretsManagerAdapter(
        secrets_mount_path=str(tmp_path),
        client=fake_client,
    )
    assert adapter._resolve_mounted_path("key") is None


def test_aws_secrets_manager_custom_path_resolver(tmp_path: Path) -> None:
    class CustomResolver:
        def resolve(self, mount_root: Path, vault_ref: str) -> Path | None:
            return mount_root / "custom_mount" / vault_ref

    adapter = AwsSecretsManagerAdapter(
        secrets_mount_path=str(tmp_path),
        path_resolver=CustomResolver(),
    )
    assert adapter._resolve_mounted_path("key") == tmp_path / "custom_mount" / "key"


@pytest.mark.asyncio
async def test_aws_secrets_manager_store_private_key(tmp_path: Path) -> None:
    fake_client = FakeSecretsManagerClient()
    adapter = AwsSecretsManagerAdapter(
        secrets_mount_path=str(tmp_path),
        client=fake_client,
        secrets_prefix="stage/tenant-1",
    )

    pem_bytes = b"PEM_PRIVATE_KEY"
    ref = await adapter.store_private_key(pem_bytes, category="partners")
    assert ref.startswith("stage/tenant-1/partners/")
    assert len(fake_client.created_secrets) == 1
    assert fake_client.created_secrets[0]["SecretString"] == "PEM_PRIVATE_KEY"

    # Default category fallback
    ref_default = await adapter.store_private_key(pem_bytes, category=None)
    assert ref_default.startswith("stage/tenant-1/keys/")


@pytest.mark.asyncio
async def test_aws_secrets_manager_fetch_from_aws_formats(tmp_path: Path) -> None:
    fake_client = FakeSecretsManagerClient(
        responses={
            "str_key": {"SecretString": "hello_secret"},
            "bytes_key": {"SecretBinary": b"binary_bytes"},
            "bytearray_key": {"SecretBinary": bytearray(b"bytearray_val")},
            "bin_str_key": {"SecretBinary": "bin_as_string"},
            "empty_key": {},
            "not_found": ClientError(
                {"Error": {"Code": "ResourceNotFoundException", "Message": "NotFound"}},
                "GetSecretValue",
            ),
            "marked_deleted": ClientError(
                {"Error": {"Code": "InvalidRequestException", "Message": "marked for deletion"}},
                "GetSecretValue",
            ),
            "internal_err": ClientError(
                {"Error": {"Code": "InternalServiceError", "Message": "AWS Error"}},
                "GetSecretValue",
            ),
        }
    )
    adapter = AwsSecretsManagerAdapter(
        secrets_mount_path=str(tmp_path / "unmounted"),
        client=fake_client,
    )

    assert await adapter.retrieve_secret("str_key") == b"hello_secret"
    assert await adapter.retrieve_secret("bytes_key") == b"binary_bytes"
    assert await adapter.retrieve_secret("bytearray_key") == b"bytearray_val"
    assert await adapter.retrieve_secret("bin_str_key") == b"bin_as_string"

    # string & private key helpers
    assert await adapter.get_secret("str_key") == "hello_secret"
    assert await adapter.retrieve_private_key("str_key") == b"hello_secret"

    with pytest.raises(ValueError, match="Secret value is empty"):
        await adapter.retrieve_secret("empty_key")

    with pytest.raises(ValueError, match="Secret not found: not_found"):
        await adapter.retrieve_secret("not_found")

    with pytest.raises(ValueError, match="Secret not found: marked_deleted"):
        await adapter.retrieve_secret("marked_deleted")

    with pytest.raises(ClientError):
        await adapter.retrieve_secret("internal_err")


@pytest.mark.asyncio
async def test_aws_secrets_manager_caching_and_ttl(tmp_path: Path) -> None:
    fake_client = FakeSecretsManagerClient()
    adapter = AwsSecretsManagerAdapter(
        secrets_mount_path=str(tmp_path),
        client=fake_client,
    )
    adapter._cache_max_size = 2
    adapter._cache_ttl_seconds = 3600

    # 1. First retrieve populates cache
    val1 = await adapter.retrieve_secret("key1")
    assert val1 == b"mock_secret"
    assert "key1" in adapter._cache

    # 2. Second retrieve hits cache
    val2 = await adapter.retrieve_secret("key1")
    assert val2 == b"mock_secret"

    # 3. Simulate TTL expiration
    adapter._cache["key1"] = (b"old_secret", 0.0)  # expired
    val3 = await adapter.retrieve_secret("key1")
    assert val3 == b"mock_secret"

    # 4. Fill cache to trigger eviction on exceeding max_size
    await adapter.retrieve_secret("key2")
    assert len(adapter._cache) == 2
    await adapter.retrieve_secret("key3")
    # Cache cleared and only new key added
    assert len(adapter._cache) == 1
    assert "key3" in adapter._cache


@pytest.mark.asyncio
async def test_aws_secrets_manager_delete_error_handling(tmp_path: Path) -> None:
    fake_client = FakeSecretsManagerClient(
        responses={
            "not_found": ClientError(
                {"Error": {"Code": "ResourceNotFoundException", "Message": "NotFound"}},
                "DeleteSecret",
            ),
            "marked_deleted": ClientError(
                {"Error": {"Code": "InvalidRequestException", "Message": "marked for deletion"}},
                "DeleteSecret",
            ),
            "other_err": ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "Denied"}},
                "DeleteSecret",
            ),
        }
    )
    adapter = AwsSecretsManagerAdapter(
        secrets_mount_path=str(tmp_path / "nonexistent"),
        client=fake_client,
    )

    # Swallows NotFound and marked for deletion
    await adapter.delete_secret("not_found")
    await adapter.delete_secret("marked_deleted")

    with pytest.raises(ClientError):
        await adapter.delete_secret("other_err")


def test_secret_store_provider_resolves_aws(tmp_path: Path) -> None:
    store = SecretStoreProvider.get_secret_store(
        secrets_mount_path=str(tmp_path),
        backend=SecretStoreBackend.AWS,
    )
    assert isinstance(store, AwsSecretsManagerAdapter)
    assert isinstance(store._path_resolver, MountedSecretPathResolver)


def test_secret_store_provider_unsupported_backend() -> None:
    with pytest.raises(ValueError, match="Unsupported SECRETS_BACKEND 'unknown'"):
        SecretStoreProvider.get_secret_store(backend="unknown")


def test_secret_store_provider_unimplemented_backend() -> None:
    with pytest.raises(NotImplementedError, match="backend 'vault' is architecturally supported"):
        SecretStoreProvider.get_secret_store(backend=SecretStoreBackend.VAULT)


def test_register_secret_store_backend(tmp_path: Path) -> None:
    try:
        fake_vault = InMemoryVaultAdapter()
        SecretStoreProvider.register_secret_store_backend(
            SecretStoreBackend.VAULT,
            lambda **kwargs: fake_vault,
        )
        resolved = SecretStoreProvider.get_secret_store(
            secrets_mount_path=str(tmp_path),
            backend=SecretStoreBackend.VAULT,
        )
        assert resolved is fake_vault
    finally:
        SecretStoreProvider.reset_registry()
