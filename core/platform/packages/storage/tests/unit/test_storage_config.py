"""Unit tests for centralized PlatformStorageSettings and StorageProvider.from_settings."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from seedwork.infra import config as seedwork_config
from seedwork.infra.config_models import PlatformAwsSettings
from seedwork.infra.repo_root import find_repo_root
from storage.adapters.file_system_storage_adapter import FileSystemPayloadStorage
from storage.adapters.s3_storage_adapter import Aioboto3PayloadStorage
from storage.config import PlatformStorageSettings
from storage.domain.enums import StorageBackend
from storage.provider import StorageProvider


def test_relative_storage_file_path_anchors_to_repo_root() -> None:
    expected = str((find_repo_root(Path(__file__).resolve()) / ".local/storage").resolve())
    settings = PlatformStorageSettings(
        backend=StorageBackend.FILE,
        file_path=".local/storage",
    )
    assert settings.file_path == expected
    assert settings.resolved_backend == StorageBackend.FILE


def test_relative_storage_file_path_fails_fast_outside_monorepo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _no_repo_root(_start: Path) -> Path:
        raise RuntimeError("no git root in container")

    monkeypatch.setattr(seedwork_config, "find_repo_root", _no_repo_root)

    with pytest.raises(ValidationError, match="must be an absolute path"):
        PlatformStorageSettings(
            backend=StorageBackend.FILE,
            file_path=".local/storage",
        )


def test_storage_provider_from_settings_builds_file_adapter(tmp_path: Path) -> None:
    target = tmp_path / "payloads"
    settings = PlatformStorageSettings(
        backend=StorageBackend.FILE,
        file_path=str(target),
    )
    storage = StorageProvider.from_settings(settings)
    assert isinstance(storage, FileSystemPayloadStorage)
    assert storage.base_directory == target.resolve()


def test_storage_provider_from_settings_builds_s3_adapter() -> None:
    settings = PlatformStorageSettings(
        backend=StorageBackend.S3,
        bucket="enterprise-edi-payloads",
        region="us-west-2",
        endpoint_url="http://minio:9000",
    )
    storage = StorageProvider.from_settings(settings)
    assert isinstance(storage, Aioboto3PayloadStorage)
    assert storage.bucket == "enterprise-edi-payloads"
    assert storage.region == "us-west-2"
    assert storage.endpoint_url == "http://minio:9000"


def test_create_payload_storage_honors_explicit_base_directory_without_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("STORAGE_FILE_PATH", raising=False)
    monkeypatch.delenv("PAYLOAD_STORAGE_PATH", raising=False)

    target = tmp_path / "explicit-dir"
    storage = StorageProvider.create_payload_storage(base_directory=target)
    assert isinstance(storage, FileSystemPayloadStorage)
    assert storage.base_directory == target.resolve()


def test_s3_storage_rejects_dummy_local_credentials_without_endpoint() -> None:
    settings = PlatformStorageSettings(
        backend=StorageBackend.S3,
        bucket="edi-as2-payloads",
        endpoint_url=None,
    )
    dummy_aws = PlatformAwsSettings(
        endpoint_url=None,
        access_key_id="test",
        secret_access_key="test",
    )

    with pytest.raises(ValueError, match="dummy local AWS_ACCESS_KEY_ID='test'"):
        StorageProvider.from_settings(settings, aws_settings=dummy_aws)
