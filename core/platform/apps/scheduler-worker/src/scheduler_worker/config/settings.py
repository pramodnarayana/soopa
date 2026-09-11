import typing
from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from seedwork.infrastructure.config import load_settings_safely
from seedwork.infrastructure.config_models import (
    PlatformAwsSettings,
    PlatformDatabaseSettings,
)


class SqsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    data_plane_jobs_queue_url: str = Field(
        validation_alias="SQS_DATA_PLANE_JOBS_QUEUE_URL", default=""
    )
    control_plane_jobs_queue_url: str = Field(
        validation_alias="SQS_CONTROL_PLANE_JOBS_QUEUE_URL", default=""
    )
    notification_jobs_queue_url: str = Field(
        validation_alias="SQS_NOTIFICATION_JOBS_QUEUE_URL", default=""
    )


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    scheduler_poll_interval_seconds: int = Field(
        validation_alias="SCHEDULER_POLL_INTERVAL_SECONDS", default=5, gt=0
    )
    scheduler_max_concurrent_jobs: int = Field(
        validation_alias="SCHEDULER_MAX_CONCURRENT_JOBS", default=10, gt=0
    )

    database: PlatformDatabaseSettings = Field(
        default_factory=lambda: typing.cast(PlatformDatabaseSettings, {})
    )
    aws: PlatformAwsSettings = Field(default_factory=lambda: typing.cast(PlatformAwsSettings, {}))
    sqs: SqsSettings = Field(default_factory=lambda: typing.cast(SqsSettings, {}))

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
    def sqs_notification_jobs_queue_url(self) -> str:
        return self.sqs.notification_jobs_queue_url

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
