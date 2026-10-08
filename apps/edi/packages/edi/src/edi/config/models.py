import ipaddress
import typing
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import (
    PlatformAwsSettings,
    PlatformDatabaseSettings,
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

    sns_topic_arn: str = Field(validation_alias="SNS_PLATFORM_EVENTS_TOPIC_ARN", default="")


class EdiDataPlaneSqsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    orchestrator_queue_url: str = Field(
        validation_alias="SQS_ORCHESTRATOR_QUEUE_URL",
        description="The SQS queue URL for EDI Orchestrator (Transform & Lifecycle)",
    )
    compute_queue_url: str = Field(
        validation_alias="SQS_COMPUTE_QUEUE_URL",
        description="The SQS queue URL for EDI Compute (BOTS)",
    )
    deliver_queue_url: str = Field(
        validation_alias="SQS_DELIVER_QUEUE_URL", description="The SQS queue URL for EDI Deliver"
    )
    data_plane_jobs_queue_url: str = Field(
        validation_alias="SQS_DATA_PLANE_JOBS_QUEUE_URL",
        description="The SQS queue URL for EDI Data Plane Jobs",
    )


class EdiControlPlaneSqsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    provisioning_queue_url: str = Field(
        validation_alias="SQS_PROVISIONING_QUEUE_URL",
        description="The SQS queue URL for EDI Config Sync/Provisioning",
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


class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    env: Literal["development", "staging", "production"] = Field(
        validation_alias="ENV", default="development"
    )
    edi_environment: Literal["P", "T", "I"] = Field(
        validation_alias="EDI_ENVIRONMENT",
        description="EDI Environment flag (Production, Test, Information)",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        validation_alias="LOG_LEVEL", default="INFO"
    )
    allow_private_ips: bool = Field(
        validation_alias="EDI_ALLOW_PRIVATE_IPS",
        default=False,
        description="Allow private IPs in AS2/HTTP delivery (for local docker testing)",
    )
    database: PlatformDatabaseSettings = Field(default_factory=PlatformDatabaseSettings)
    otel: PlatformOtelSettings = Field(
        default_factory=lambda: typing.cast(PlatformOtelSettings, {})
    )
    public: PublicSettings = Field(default_factory=lambda: typing.cast(PublicSettings, {}))

    @model_validator(mode="after")
    def validate_and_resolve_settings(self) -> "CommonSettings":
        if self.env != "development":
            if self.allow_private_ips:
                raise ValueError("allow_private_ips must be False in non-development environments")

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
            except ValueError:
                ip = None

            if ip and (ip.is_loopback or ip.is_unspecified):
                raise ValueError(
                    "base_url must not be a loopback address in non-development environments"
                )

        return self


@lru_cache
def get_worker_settings() -> CommonSettings:
    return load_settings_safely(CommonSettings)
