"""Unit tests for centralized PlatformSecretStoreSettings, fail-fast invariants, and directory security."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from pydantic import ValidationError
from secret_store.adapters.file_system_secret_store import FileSystemSecretStoreAdapter
from secret_store.config import PlatformSecretStoreSettings
from secret_store.domain.enums import SecretStoreBackend
from secret_store.provider import SecretStoreProvider
from seedwork.infra import config as seedwork_config
from seedwork.infra.config_models import PlatformAwsSettings
from seedwork.infra.repo_root import find_repo_root


def test_secret_store_backend_requires_sync_sidecar_policy() -> None:
    assert SecretStoreBackend.AWS.requires_sync_sidecar is True
    assert SecretStoreBackend.GCP.requires_sync_sidecar is True
    assert SecretStoreBackend.AZURE.requires_sync_sidecar is True
    assert SecretStoreBackend.FILE.requires_sync_sidecar is False
    assert SecretStoreBackend.KUBERNETES.requires_sync_sidecar is False
    assert SecretStoreBackend.VAULT.requires_sync_sidecar is False


def test_relative_mount_path_anchors_deterministically_to_repo_root() -> None:
    expected = str((find_repo_root(Path(__file__).resolve()) / ".local/secrets").resolve())
    settings = PlatformSecretStoreSettings(
        backend=SecretStoreBackend.FILE,
        mount_path=".local/secrets",
    )
    assert settings.mount_path == expected


def test_relative_mount_path_fails_fast_outside_monorepo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _no_repo_root(_start: Path) -> Path:
        raise RuntimeError("no git root in container")

    monkeypatch.setattr(seedwork_config, "find_repo_root", _no_repo_root)

    with pytest.raises(ValidationError, match="must be an absolute path"):
        PlatformSecretStoreSettings(
            backend=SecretStoreBackend.FILE,
            mount_path=".local/secrets",
        )


def test_vault_backend_requires_vault_url() -> None:
    with pytest.raises(ValidationError, match="VAULT_ADDR"):
        PlatformSecretStoreSettings(
            backend=SecretStoreBackend.VAULT,
            mount_path="/mnt/secrets",
            vault_url=None,
        )


def test_aws_backend_rejects_dummy_local_credentials_without_endpoint() -> None:
    settings = PlatformSecretStoreSettings(
        backend=SecretStoreBackend.AWS,
        mount_path="/mnt/secrets",
    )
    dummy_aws = PlatformAwsSettings(
        endpoint_url=None,
        access_key_id="test",
        secret_access_key="test",
    )

    with pytest.raises(ValueError, match="dummy local AWS_ACCESS_KEY_ID='test'"):
        SecretStoreProvider.from_settings(settings, aws_settings=dummy_aws)


def test_from_settings_resolves_file_backend(tmp_path: Path) -> None:
    settings = PlatformSecretStoreSettings(
        backend=SecretStoreBackend.FILE,
        mount_path=str(tmp_path / "vault"),
        prefix="edi",
    )
    store = SecretStoreProvider.from_settings(settings)
    assert isinstance(store, FileSystemSecretStoreAdapter)


async def test_file_system_secret_store_enforces_0700_dirs_and_0600_files(
    tmp_path: Path,
) -> None:
    mount_dir = tmp_path / "secure-secrets"
    store = SecretStoreProvider.from_settings(
        PlatformSecretStoreSettings(
            backend=SecretStoreBackend.FILE,
            mount_path=str(mount_dir),
        )
    )

    ref = await store.store_private_key(b"-----BEGIN PRIVATE KEY-----\ntest\n", category="as2_key")
    key_file = mount_dir / ref

    assert stat.S_IMODE(mount_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(key_file.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
