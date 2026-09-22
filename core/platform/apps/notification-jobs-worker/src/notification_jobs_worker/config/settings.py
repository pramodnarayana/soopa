from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import (
    PlatformAwsSettings,
    PlatformDatabaseSettings,
)


class NotificationOutboxAwsSettings(PlatformAwsSettings):
    sns_topic_arn: str = Field(validation_alias="SNS_PLATFORM_EVENTS_TOPIC_ARN")


class SqsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    notification_jobs_queue_url: str = Field(
        validation_alias="SQS_NOTIFICATION_JOBS_QUEUE_URL", default=""
    )


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database: PlatformDatabaseSettings = Field(
        default_factory=lambda: PlatformDatabaseSettings(global_url="")
    )
    aws: NotificationOutboxAwsSettings = Field(
        default_factory=lambda: NotificationOutboxAwsSettings(sns_topic_arn="")
    )
    sqs: SqsSettings = Field(default_factory=lambda: SqsSettings())

    @computed_field
    @property
    def database_url(self) -> str:
        return self.database.global_url

    @computed_field
    @property
    def sns_topic_arn(self) -> str:
        return self.aws.sns_topic_arn

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
