import ipaddress
import typing
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from seedwork.infrastructure.config import load_settings_safely
from seedwork.infrastructure.config_models import (
    PlatformAwsSettings,
    PlatformDatabaseSettings,
    PlatformIdentitySettings,
    PlatformOtelSettings,
)

from edi.config.constants import SECRETS_MOUNT_PATH

"""
Shared application settings for all EDI AS2 services.
All settings are loaded from environment variables and validated by Pydantic.
Each service can use the full AppSettings or cherry-pick specific groups.
"""


class S3Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    bucket: str = Field(validation_alias="S3_BUCKET", default="edi-as2-payloads")
    endpoint_url: str | None = Field(
        validation_alias="S3_ENDPOINT_URL",
        default=None,
        description="Override for MinIO or other S3-compatible stores. Leave empty for AWS S3.",
    )
    region: str = Field(validation_alias="S3_REGION", default="us-east-1")
    access_key_id: str | None = Field(validation_alias="S3_ACCESS_KEY_ID", default=None)
    secret_access_key: str | None = Field(validation_alias="S3_SECRET_ACCESS_KEY", default=None)


class EdiAwsSettings(PlatformAwsSettings):
    """
    Extends the base PlatformAwsSettings to include EDI-specific topics.
    """

    sns_topic_arn: str = Field(validation_alias="SNS_EDI_EVENTS_TOPIC_ARN", default="")


class SqsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    provisioning_queue_url: str = Field(
        validation_alias="SQS_PROVISIONING_QUEUE_URL",
        description="The SQS queue URL for EDI Config Sync/Provisioning",
    )
    transform_queue_url: str = Field(
        validation_alias="SQS_TRANSFORM_QUEUE_URL",
        description="The SQS queue URL for EDI Transform",
    )
    lifecycle_queue_url: str = Field(
        validation_alias="SQS_LIFECYCLE_QUEUE_URL",
        description="The SQS queue URL for EDI Lifecycle",
    )
    deliver_queue_url: str = Field(
        validation_alias="SQS_DELIVER_QUEUE_URL", description="The SQS queue URL for EDI Deliver"
    )
    data_plane_jobs_queue_url: str = Field(
        validation_alias="SQS_DATA_PLANE_JOBS_QUEUE_URL",
        description="The SQS queue URL for EDI Data Plane Jobs",
    )
    control_plane_jobs_queue_url: str = Field(
        validation_alias="SQS_CONTROL_PLANE_JOBS_QUEUE_URL",
        description="The SQS queue URL for EDI Control Plane Jobs",
    )


class PublicSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    base_url: str = Field(
        validation_alias="PUBLIC_BASE_URL",
        description="The external base URL of the EDI platform",
    )


class SecretsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mount_path: str = Field(validation_alias="SECRETS_MOUNT_PATH", default=SECRETS_MOUNT_PATH)
    sync_interval_seconds: int = Field(
        validation_alias="SECRETS_SYNC_INTERVAL_SECONDS", default=300
    )


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    env: Literal["development", "staging", "production"] = Field(
        validation_alias="ENV", default="development"
    )
    enable_heavy_compute_queue: bool = Field(
        validation_alias="ENABLE_HEAVY_COMPUTE_QUEUE",
        default=False,
        description="Feature flag to route heavy EDI parsing to a dedicated compute queue.",
    )
    edi_environment: Literal["P", "T", "I"] = Field(
        validation_alias="EDI_ENVIRONMENT",
        default="P",
        description="EDI Environment flag (Production, Test, Information)",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        validation_alias="LOG_LEVEL", default="INFO"
    )
    storage_backend: Literal["postgres", "s3"] = Field(
        validation_alias="STORAGE_BACKEND", default="postgres"
    )

    database: PlatformDatabaseSettings = Field(
        default_factory=lambda: typing.cast(PlatformDatabaseSettings, {})
    )
    s3: S3Settings = Field(default_factory=lambda: typing.cast(S3Settings, {}))
    aws: EdiAwsSettings = Field(default_factory=lambda: typing.cast(EdiAwsSettings, {}))
    sqs: SqsSettings = Field(default_factory=lambda: typing.cast(SqsSettings, {}))
    otel: PlatformOtelSettings = Field(
        default_factory=lambda: typing.cast(PlatformOtelSettings, {})
    )
    identity: PlatformIdentitySettings = Field(
        default_factory=lambda: typing.cast(PlatformIdentitySettings, {})
    )
    public: PublicSettings = Field(default_factory=lambda: typing.cast(PublicSettings, {}))
    secrets: SecretsSettings = Field(default_factory=lambda: typing.cast(SecretsSettings, {}))

    @model_validator(mode="after")
    def validate_external_url(self) -> "AppSettings":
        if self.env != "development":
            if "://" not in self.public.base_url:
                raise ValueError("base_url must include a scheme (e.g. https://)")

            parsed = urlparse(self.public.base_url)
            host = parsed.hostname or ""

            if host == "localhost":
                raise ValueError(
                    "base_url must not be a loopback address in non-development environments"
                )

            try:
                ip = ipaddress.ip_address(host)
                if ip.is_loopback or ip.is_unspecified:
                    raise ValueError(
                        "base_url must not be a loopback address in non-development environments"
                    )
            except ValueError:
                pass

        return self


@lru_cache
def get_settings() -> AppSettings:
    """
    Returns the cached application settings singleton.
    Decorated with @lru_cache so settings are only parsed once per process.
    """

    return load_settings_safely(AppSettings)
