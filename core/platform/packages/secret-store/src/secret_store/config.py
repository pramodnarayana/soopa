"""Centralized configuration model for the secret-store platform capability package."""

from __future__ import annotations

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import SettingsConfigDict
from seedwork.infra.config import CleanBaseSettings, resolve_anchored_path
from seedwork.infra.config_models import PlatformAwsSettings

from secret_store.domain.enums import SecretStoreBackend

DEFAULT_SECRETS_MOUNT_PATH = "/mnt/secrets"
DEFAULT_SECRETS_SYNC_INTERVAL_SECONDS = 300
DEFAULT_VAULT_MOUNT_POINT = "secret"
DUMMY_LOCAL_AWS_ACCESS_KEY = "test"


class PlatformSecretStoreSettings(CleanBaseSettings):
    """Single source of truth for secret-store configuration across all apps and workers.

    Mirrors ``PlatformPubSubSettings`` and ``PlatformIdentitySettings``: validates backend
    selection, deterministically anchors relative mount paths to the monorepo root, and
    enforces fail-fast backend invariants at container boot.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    backend: SecretStoreBackend = Field(
        validation_alias="SECRETS_BACKEND",
        default=SecretStoreBackend.AWS,
    )
    mount_path: str = Field(
        validation_alias="SECRETS_MOUNT_PATH",
        default=DEFAULT_SECRETS_MOUNT_PATH,
    )
    prefix: str = Field(
        validation_alias="SECRETS_PREFIX",
        default="",
    )
    filter_prefix: str = Field(
        validation_alias="SECRETS_FILTER_PREFIX",
        default="",
    )
    vault_url: str | None = Field(
        validation_alias=AliasChoices("VAULT_ADDR", "VAULT_URL"),
        default=None,
    )
    vault_token: str | None = Field(
        validation_alias="VAULT_TOKEN",
        default=None,
    )
    vault_mount_point: str = Field(
        validation_alias="VAULT_MOUNT_POINT",
        default=DEFAULT_VAULT_MOUNT_POINT,
    )
    sync_interval_seconds: int = Field(
        validation_alias="SECRETS_SYNC_INTERVAL_SECONDS",
        default=DEFAULT_SECRETS_SYNC_INTERVAL_SECONDS,
        gt=0,
    )

    @field_validator("backend", mode="before")
    @classmethod
    def _normalize_backend(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized or SecretStoreBackend.AWS
        return value

    @field_validator("mount_path", mode="after")
    @classmethod
    def _anchor_mount_path(cls, value: str) -> str:
        return resolve_anchored_path(value, setting_name="SECRETS_MOUNT_PATH")

    @field_validator("prefix", "vault_mount_point", mode="after")
    @classmethod
    def _normalize_path_segment(cls, value: str) -> str:
        return value.strip().strip("/")

    @field_validator("filter_prefix", mode="after")
    @classmethod
    def _normalize_filter_prefix(cls, value: str) -> str:
        return value.strip()

    @field_validator("vault_url", "vault_token", mode="before")
    @classmethod
    def _normalize_optional_str(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def _validate_backend_invariants(self) -> PlatformSecretStoreSettings:
        if self.backend == SecretStoreBackend.VAULT and not self.vault_url:
            raise ValueError("VAULT_ADDR (or VAULT_URL) is required when SECRETS_BACKEND='vault'.")
        return self

    def validate_against_aws(self, aws_settings: PlatformAwsSettings) -> None:
        """Fail fast at startup if AWS backend is paired with dummy local credentials."""
        if self.backend != SecretStoreBackend.AWS:
            return
        endpoint = (aws_settings.endpoint_url or "").strip()
        access_key = (aws_settings.access_key_id or "").strip().lower()
        if not endpoint and access_key == DUMMY_LOCAL_AWS_ACCESS_KEY:
            raise ValueError(
                "SECRETS_BACKEND='aws' cannot run with dummy local AWS_ACCESS_KEY_ID='test' "
                "and no AWS_ENDPOINT_URL. Set SECRETS_BACKEND=file (with SECRETS_MOUNT_PATH) "
                "for local development, or configure real AWS credentials / IAM role."
            )
