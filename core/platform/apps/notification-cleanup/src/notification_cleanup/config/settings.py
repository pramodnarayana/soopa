from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from seedwork.infrastructure.config import load_settings_safely
from seedwork.infrastructure.config_models import (
    PlatformAwsSettings,
    PlatformDatabaseSettings,
)


class NotificationCleanupAwsSettings(PlatformAwsSettings):
    sns_topic_arn: str = Field(validation_alias="SNS_TOPIC_ARN")


class SqsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    notification_jobs_queue_url: str = Field(validation_alias="SQS_NOTIFICATION_JOBS_QUEUE_URL")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database: PlatformDatabaseSettings = Field(
        default_factory=lambda: PlatformDatabaseSettings.model_validate({})
    )
    aws: NotificationCleanupAwsSettings = Field(
        default_factory=lambda: NotificationCleanupAwsSettings.model_validate({})
    )
    sqs: SqsSettings = Field(default_factory=lambda: SqsSettings.model_validate({}))

    @property
    @computed_field
    def database_url(self) -> str:
        return self.database.global_url

    @property
    @computed_field
    def sns_topic_arn(self) -> str:
        return self.aws.sns_topic_arn

    @property
    @computed_field
    def sqs_notification_jobs_queue_url(self) -> str:
        return self.sqs.notification_jobs_queue_url

    @property
    @computed_field
    def aws_endpoint_url(self) -> str | None:
        return self.aws.endpoint_url

    @property
    @computed_field
    def aws_region(self) -> str:
        return self.aws.resolved_region


@lru_cache
def get_settings() -> AppSettings:
    return load_settings_safely(AppSettings)
