from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from seedwork.infrastructure.config import load_settings_safely
from seedwork.infrastructure.config_models import (
    PlatformAwsSettings,
    PlatformDatabaseSettings,
)


class SqsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    priority_notifications_queue_url: str = Field(
        validation_alias="SQS_PRIORITY_NOTIFICATIONS_QUEUE_URL", default=""
    )


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database: PlatformDatabaseSettings = Field(
        default_factory=lambda: PlatformDatabaseSettings(global_url="")
    )
    aws: PlatformAwsSettings = Field(default_factory=lambda: PlatformAwsSettings())
    sqs: SqsSettings = Field(default_factory=lambda: SqsSettings())

    @property
    def database_url(self) -> str:
        return self.database.global_url

    @property
    def sqs_priority_notifications_queue_url(self) -> str:
        return self.sqs.priority_notifications_queue_url

    @property
    def aws_endpoint_url(self) -> str | None:
        return self.aws.endpoint_url

    @property
    def aws_region(self) -> str:
        return self.aws.resolved_region


@lru_cache
def get_settings() -> AppSettings:
    return load_settings_safely(AppSettings)
