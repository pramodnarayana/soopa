"""Centralized configuration model for the storage platform capability package."""

from __future__ import annotations

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import SettingsConfigDict
from seedwork.infra.config import CleanBaseSettings, resolve_anchored_path
from seedwork.infra.config_models import PlatformAwsSettings

from storage.domain.enums import StorageBackend

DEFAULT_STORAGE_BUCKET = "edi-as2-payloads"
DEFAULT_STORAGE_FILE_PATH = "/mnt/storage"
DEFAULT_STORAGE_REGION = "us-east-1"
DUMMY_LOCAL_AWS_ACCESS_KEY = "test"


class PlatformStorageSettings(CleanBaseSettings):
    """Single source of truth for cloud-agnostic payload storage configuration.

    Supports both POSIX/NFS/local filesystem backends (``STORAGE_BACKEND=file``) and
    S3-compatible object stores (AWS S3, MinIO) without cloud-coupled app settings.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    backend: StorageBackend | None = Field(
        validation_alias="STORAGE_BACKEND",
        default=None,
    )
    file_path: str | None = Field(
        validation_alias=AliasChoices("PAYLOAD_STORAGE_PATH", "STORAGE_FILE_PATH"),
        default=None,
    )
    bucket: str = Field(
        validation_alias="S3_BUCKET",
        default=DEFAULT_STORAGE_BUCKET,
    )
    endpoint_url: str | None = Field(
        validation_alias="S3_ENDPOINT_URL",
        default=None,
        description="Override for MinIO or other S3-compatible stores. Leave empty for AWS S3.",
    )
    region: str = Field(
        validation_alias="S3_REGION",
        default=DEFAULT_STORAGE_REGION,
    )
    access_key_id: str | None = Field(
        validation_alias="S3_ACCESS_KEY_ID",
        default=None,
    )
    secret_access_key: str | None = Field(
        validation_alias="S3_SECRET_ACCESS_KEY",
        default=None,
    )

    @field_validator("backend", mode="before")
    @classmethod
    def _normalize_backend(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized or None
        return value

    @field_validator("file_path", mode="before")
    @classmethod
    def _normalize_and_anchor_file_path(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None
            return resolve_anchored_path(cleaned, setting_name="STORAGE_FILE_PATH")
        return value

    @field_validator("endpoint_url", "access_key_id", "secret_access_key", mode="before")
    @classmethod
    def _normalize_optional_str(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @property
    def resolved_backend(self) -> StorageBackend:
        """Resolves effective backend: explicit backend -> file (if file_path set) -> s3."""
        if self.backend is not None:
            return self.backend
        if self.file_path:
            return StorageBackend.FILE
        return StorageBackend.S3

    @property
    def resolved_file_path(self) -> str:
        """Resolves the active filesystem root directory when using a filesystem backend."""
        return self.file_path or DEFAULT_STORAGE_FILE_PATH

    def validate_against_aws(self, aws_settings: PlatformAwsSettings) -> None:
        """Fail fast at startup if S3 backend is paired with dummy local credentials."""
        if self.resolved_backend != StorageBackend.S3:
            return
        endpoint = (self.endpoint_url or aws_settings.endpoint_url or "").strip()
        access_key = (self.access_key_id or aws_settings.access_key_id or "").strip().lower()
        if not endpoint and access_key == DUMMY_LOCAL_AWS_ACCESS_KEY:
            raise ValueError(
                "STORAGE_BACKEND='s3' cannot run with dummy local AWS_ACCESS_KEY_ID='test' "
                "and no S3_ENDPOINT_URL / AWS_ENDPOINT_URL. Set STORAGE_BACKEND=file "
                "(with STORAGE_FILE_PATH) for local development, or configure real S3 credentials / IAM role."
            )
