from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import (
    PlatformAwsSettings,
    PlatformDatabaseSettings,
)


def extract_physical_queue_name(queue_url: str) -> str:
    """Extracts the physical SQS queue name from the final path segment of a QueueUrl."""
    stripped = queue_url.strip().rstrip("/")
    if not stripped or "/" not in stripped:
        return ""
    return stripped.rsplit("/", 1)[-1]


def discover_jobs_queue_url_map(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Dynamically discovers all SQS_*_JOBS_QUEUE_URL environment variables and maps physical queue names to URLs."""
    source = environ if environ is not None else os.environ
    queue_map: dict[str, str] = {}
    for key, value in source.items():
        if key.startswith("SQS_") and key.endswith("_JOBS_QUEUE_URL") and value.strip():
            physical_name = extract_physical_queue_name(value)
            if physical_name:
                queue_map[physical_name] = value.strip()
    return queue_map


class SqsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    data_plane_jobs_queue_url: str = Field(
        validation_alias="SQS_DATA_PLANE_JOBS_QUEUE_URL", default=""
    )
    control_plane_jobs_queue_url: str = Field(
        validation_alias="SQS_CONTROL_PLANE_JOBS_QUEUE_URL", default=""
    )
    ip_data_plane_jobs_queue_url: str = Field(
        validation_alias="SQS_IP_DATA_PLANE_JOBS_QUEUE_URL", default=""
    )
    ip_control_plane_jobs_queue_url: str = Field(
        validation_alias="SQS_IP_CONTROL_PLANE_JOBS_QUEUE_URL", default=""
    )
    notification_jobs_queue_url: str = Field(
        validation_alias="SQS_NOTIFICATION_JOBS_QUEUE_URL", default=""
    )
    identity_jobs_queue_url: str = Field(validation_alias="SQS_IDENTITY_JOBS_QUEUE_URL", default="")
    ucp_jobs_queue_url: str = Field(validation_alias="SQS_UCP_JOBS_QUEUE_URL", default="")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    scheduler_poll_interval_seconds: int = Field(
        validation_alias="SCHEDULER_POLL_INTERVAL_SECONDS", default=5, gt=0
    )
    scheduler_max_concurrent_jobs: int = Field(
        validation_alias="SCHEDULER_MAX_CONCURRENT_JOBS", default=10, gt=0
    )

    database: PlatformDatabaseSettings = Field(default_factory=PlatformDatabaseSettings)
    aws: PlatformAwsSettings = Field(default_factory=PlatformAwsSettings)
    sqs: SqsSettings = Field(default_factory=SqsSettings)

    @computed_field
    @property
    def database_url(self) -> str:
        return self.database.global_url

    @computed_field
    @property
    def async_database_url(self) -> str:
        return self.database.global_url

    @computed_field
    @property
    def sqs_data_plane_jobs_queue_url(self) -> str:
        return self.sqs.data_plane_jobs_queue_url

    @computed_field
    @property
    def sqs_control_plane_jobs_queue_url(self) -> str:
        return self.sqs.control_plane_jobs_queue_url

    @computed_field
    @property
    def sqs_ip_data_plane_jobs_queue_url(self) -> str:
        return self.sqs.ip_data_plane_jobs_queue_url

    @computed_field
    @property
    def sqs_ip_control_plane_jobs_queue_url(self) -> str:
        return self.sqs.ip_control_plane_jobs_queue_url

    @computed_field
    @property
    def sqs_notification_jobs_queue_url(self) -> str:
        return self.sqs.notification_jobs_queue_url

    @computed_field
    @property
    def sqs_identity_jobs_queue_url(self) -> str:
        return self.sqs.identity_jobs_queue_url

    @computed_field
    @property
    def sqs_ucp_jobs_queue_url(self) -> str:
        return self.sqs.ucp_jobs_queue_url

    @computed_field
    @property
    def sqs_queue_url_map(self) -> dict[str, str]:
        discovered = discover_jobs_queue_url_map()
        configured_urls = (
            self.sqs.data_plane_jobs_queue_url,
            self.sqs.control_plane_jobs_queue_url,
            self.sqs.ip_data_plane_jobs_queue_url,
            self.sqs.ip_control_plane_jobs_queue_url,
            self.sqs.notification_jobs_queue_url,
            self.sqs.identity_jobs_queue_url,
            self.sqs.ucp_jobs_queue_url,
        )
        for url in configured_urls:
            physical_name = extract_physical_queue_name(url)
            if physical_name:
                discovered[physical_name] = url.strip()
        return discovered

    @computed_field
    @property
    def aws_endpoint_url(self) -> str | None:
        return self.aws.endpoint_url

    @computed_field
    @property
    def aws_region(self) -> str:
        return self.aws.resolved_region


@lru_cache
def get_settings() -> AppSettings:
    return load_settings_safely(AppSettings)
