"""Unit and narrow integration tests for sovereign FileSystem and Vault secret store adapters."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from secret_store.adapters.file_system_secret_store import FileSystemSecretStoreAdapter
from secret_store.adapters.mounted_path_resolver import MountedSecretPathResolver
from secret_store.adapters.vault_secret_store import VaultSecretStoreAdapter
from secret_store.provider import SecretStoreBackend, SecretStoreProvider


@pytest.mark.asyncio
async def test_file_system_secret_store_lifecycle(tmp_path: Path) -> None:
    store = FileSystemSecretStoreAdapter(
        secrets_mount_path=str(tmp_path),
        secrets_prefix="soopa/onprem",
        path_resolver=MountedSecretPathResolver(),
    )

    pem_bytes = b"-----BEGIN RSA PRIVATE KEY-----\nSOVEREIGN_KEY\n-----END RSA PRIVATE KEY-----"
    ref = await store.store_private_key(pem_bytes, category="as2_partner")
    assert ref.startswith("soopa/onprem/as2_partner/")
    stored_file = tmp_path / ref
    assert (stored_file.stat().st_mode & 0o777) == 0o600

    # Normalization check
    normalized = store.normalize_category_ref(f"vault://{ref}", "as2_partner")
    assert normalized == ref
    assert store.normalize_category_ref("other/as2_partner/123", "as2_partner") is None

    # Retrieval checks
    retrieved_bytes = await store.retrieve_secret(ref)
    assert retrieved_bytes == pem_bytes
    assert await store.retrieve_private_key(ref) == pem_bytes
    assert await store.get_secret(ref) == pem_bytes.decode("utf-8")

    # Delete check
    await store.delete_secret(ref)
    with pytest.raises(ValueError, match="Secret not found"):
        await store.retrieve_secret(ref)


@pytest.mark.asyncio
async def test_file_system_secret_store_security_and_edge_cases(tmp_path: Path) -> None:
    store = FileSystemSecretStoreAdapter(
        secrets_mount_path=str(tmp_path),
        path_resolver=MountedSecretPathResolver(),
    )

    # Path traversal blocked
    with pytest.raises(ValueError, match="Secret not found"):
        await store.retrieve_secret("../../etc/passwd")

    # Empty secret file raises ValueError
    empty_file = tmp_path / "keys" / "empty_key"
    empty_file.parent.mkdir(parents=True)
    empty_file.write_bytes(b"")
    with pytest.raises(ValueError, match="Secret value is empty"):
        await store.retrieve_secret("keys/empty_key")

    # Without path resolver
    store_no_resolver = FileSystemSecretStoreAdapter(
        secrets_mount_path=str(tmp_path),
        path_resolver=None,
    )
    with pytest.raises(ValueError, match="Invalid secret path reference"):
        await store_no_resolver.store_private_key(b"key_data")


@pytest.mark.asyncio
async def test_vault_secret_store_http_api_lifecycle(tmp_path: Path) -> None:
    vault_db: dict[str, dict[str, str]] = {
        "dc1/as2/remote_key": {"value": "REMOTE_VAULT_SECRET"},
        "dc1/certs/partner_cert": {"cert": "CERT_DATA"},
    }
    deleted_paths: list[str] = []

    def vault_transport_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Vault-Token") == "s.sovereign_token_123"
        prefix = "/v1/secret/data/"
        assert request.url.path.startswith(prefix)
        secret_key = request.url.path.removeprefix(prefix)

        if request.method == "GET":
            if secret_key not in vault_db:
                return httpx.Response(404, json={"errors": []})
            return httpx.Response(200, json={"data": {"data": vault_db[secret_key]}})

        if request.method == "POST":
            body = json.loads(request.content.decode("utf-8"))
            vault_db[secret_key] = body["data"]
            return httpx.Response(200, json={"data": {"version": 1}})

        if request.method == "DELETE":
            vault_db.pop(secret_key, None)
            deleted_paths.append(secret_key)
            return httpx.Response(204)

        return httpx.Response(405)

    mount_dir = tmp_path / "vault_mount"
    store = VaultSecretStoreAdapter(
        vault_url="http://vault.internal:8200",
        vault_token="s.sovereign_token_123",
        mount_point="secret",
        secrets_mount_path=str(mount_dir),
        secrets_prefix="dc1",
        path_resolver=MountedSecretPathResolver(),
        http_transport=httpx.MockTransport(vault_transport_handler),
    )

    # 1. Remote fetch from Vault KV v2 API when not in local mount
    remote_val = await store.get_secret("vault://dc1/as2/remote_key")
    assert remote_val == "REMOTE_VAULT_SECRET"

    # 2. Fetch structured dict secret from Vault KV v2 API
    json_secret = await store.retrieve_secret("dc1/certs/partner_cert")
    assert b"CERT_DATA" in json_secret

    # 3. Store private key writes to both local mount and Vault HTTP API
    stored_ref = await store.store_private_key(b"NEW_VAULT_PEM", category="as2")
    assert stored_ref.startswith("dc1/as2/")
    assert vault_db[stored_ref] == {"value": "NEW_VAULT_PEM"}
    assert (mount_dir / stored_ref).read_bytes() == b"NEW_VAULT_PEM"

    # 4. Delete removes both local mount and Vault API entry
    await store.delete_secret(stored_ref)
    assert not (mount_dir / stored_ref).exists()
    assert stored_ref in deleted_paths

    # 5. 404 from Vault API raises ValueError("Secret not found")
    with pytest.raises(ValueError, match="Secret not found"):
        await store.retrieve_secret("dc1/missing")


@pytest.mark.asyncio
async def test_vault_secret_store_local_mount_without_token_and_fail_fast_write(
    tmp_path: Path,
) -> None:
    mount_dir = tmp_path / "vault_local"
    store = VaultSecretStoreAdapter(
        vault_url="http://vault.internal:8200",
        vault_token="",
        secrets_mount_path=str(mount_dir),
        path_resolver=MountedSecretPathResolver(),
    )

    # Storing into Vault without VAULT_TOKEN must fail fast (never silently skip Vault)
    with pytest.raises(ValueError, match="VAULT_TOKEN is required"):
        await store.store_private_key(b"LOCAL_CACHED_KEY", category="sftp")

    # Reading a Vault-Agent-mounted local file without a token still works
    mounted_file = mount_dir / "sftp" / "agent_rendered_key"
    mounted_file.parent.mkdir(parents=True, exist_ok=True)
    mounted_file.write_bytes(b"LOCAL_CACHED_KEY")
    ref = "sftp/agent_rendered_key"

    assert await store.retrieve_private_key(ref) == b"LOCAL_CACHED_KEY"
    assert store.normalize_category_ref(ref, "sftp") == ref

    await store.delete_secret(ref)
    assert not mounted_file.exists()

    with pytest.raises(ValueError, match="Secret not found"):
        await store.retrieve_secret(ref)

    # Vault HTTP 500 surfaces as RuntimeError (not raw httpx.HTTPStatusError)
    error_store = VaultSecretStoreAdapter(
        vault_url="http://vault.internal:8200",
        vault_token="s.token",
        secrets_mount_path=str(mount_dir),
        path_resolver=MountedSecretPathResolver(),
        http_transport=httpx.MockTransport(lambda _req: httpx.Response(500)),
    )
    with pytest.raises(RuntimeError, match="HTTP 500"):
        await error_store.retrieve_secret("sftp/server_err")
    await error_store.aclose()


def test_secret_store_provider_resolves_sovereign_backends(tmp_path: Path) -> None:
    file_store = SecretStoreProvider.get_secret_store(
        secrets_mount_path=str(tmp_path),
        backend=SecretStoreBackend.FILE,
    )
    assert isinstance(file_store, FileSystemSecretStoreAdapter)

    k8s_store = SecretStoreProvider.get_secret_store(
        secrets_mount_path=str(tmp_path),
        backend=SecretStoreBackend.KUBERNETES,
    )
    assert isinstance(k8s_store, FileSystemSecretStoreAdapter)

    vault_store = SecretStoreProvider.get_secret_store(
        secrets_mount_path=str(tmp_path),
        backend=SecretStoreBackend.VAULT,
        vault_url="http://vault.internal:8200",
        vault_token="tok_123",
    )
    assert isinstance(vault_store, VaultSecretStoreAdapter)


@pytest.mark.asyncio
async def test_file_system_secret_store_boots_and_reads_on_readonly_mount(tmp_path: Path) -> None:
    mount_dir = tmp_path / "k8s-secrets"
    secret_file = mount_dir / "keys" / "as2_signing_key"
    secret_file.parent.mkdir(parents=True)
    secret_file.write_bytes(b"READONLY_SECRET_PAYLOAD")

    mount_dir.chmod(0o555)
    try:
        store = FileSystemSecretStoreAdapter(
            secrets_mount_path=str(mount_dir),
            path_resolver=MountedSecretPathResolver(),
        )
        assert await store.retrieve_secret("keys/as2_signing_key") == b"READONLY_SECRET_PAYLOAD"
    finally:
        mount_dir.chmod(0o755)
