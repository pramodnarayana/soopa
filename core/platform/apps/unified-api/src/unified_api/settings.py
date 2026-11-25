from functools import lru_cache
from typing import Literal, cast

from identity import PlatformIdentitySettings
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import SettingsConfigDict
from seedwork.infra.config import CleanBaseSettings, load_settings_safely
from seedwork.infra.config_models import (
    PlatformDatabaseSettings,
    PlatformOtelSettings,
)


class PlatformSecretsSettings(CleanBaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mount_path: str = Field(validation_alias="SECRETS_MOUNT_PATH", default="/mnt/secrets")
    sync_interval_seconds: int = Field(
        validation_alias="SECRETS_SYNC_INTERVAL_SECONDS", default=300
    )


class ApiSettings(CleanBaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    env: Literal["development", "staging", "production"] = Field(
        validation_alias=AliasChoices("ENV", "ENVIRONMENT"), default="development"
    )

    @field_validator("env", mode="before")
    @classmethod
    def _normalize_env_alias(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        alias_map = {
            "dev": "development",
            "local": "development",
            "test": "development",
            "stage": "staging",
            "prod": "production",
        }
        return alias_map.get(normalized, normalized)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        validation_alias="LOG_LEVEL", default="INFO"
    )
    allow_private_ips: bool = Field(
        validation_alias="EDI_ALLOW_PRIVATE_IPS",
        default=False,
    )
    database: PlatformDatabaseSettings = Field(default_factory=PlatformDatabaseSettings)
    otel: PlatformOtelSettings = Field(default_factory=lambda: cast(PlatformOtelSettings, {}))
    identity: PlatformIdentitySettings = Field(
        default_factory=lambda: cast(PlatformIdentitySettings, {})
    )
    secrets: PlatformSecretsSettings = Field(default_factory=PlatformSecretsSettings)
    cors_allowed_origins: list[str] = Field(validation_alias="CORS_ALLOWED_ORIGINS")
    enabled_apps: str = Field(
        default="edi,ip",
        validation_alias="ENABLED_APPS",
        description="Comma-separated list of enabled bounded-context API modules (e.g. 'edi,ip', 'ip', 'edi')",
    )
    as2_receive_url: str = Field(
        default="",
        validation_alias="AS2_RECEIVE_URL",
        description="The fully-qualified absolute URL for AS2 payload ingress",
    )
    config_sync_internal_token: str = Field(
        default="",
        validation_alias="CONFIG_SYNC_INTERNAL_TOKEN",
        description="Shared Bearer token authenticating Data Plane Dynamic Watch connections",
    )


@lru_cache
def get_settings() -> ApiSettings:
    return load_settings_safely(ApiSettings)
