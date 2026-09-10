import typing
from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from seedwork.infrastructure.config import load_settings_safely
from seedwork.infrastructure.config_models import (
    PlatformAwsSettings,
    PlatformDatabaseSettings,
)


class NotificationOutboxAwsSettings(PlatformAwsSettings):
    sns_topic_arn: str = Field(validation_alias="SNS_TOPIC_ARN", default="")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database: PlatformDatabaseSettings = Field(
        default_factory=lambda: typing.cast(PlatformDatabaseSettings, {})
    )
    aws: NotificationOutboxAwsSettings = Field(
        default_factory=lambda: typing.cast(NotificationOutboxAwsSettings, {})
    )

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
    def aws_endpoint_url(self) -> str | None:
        return self.aws.endpoint_url

    @computed_field
    @property
    def aws_region(self) -> str:
        return self.aws.resolved_region


@lru_cache
def get_settings() -> AppSettings:
    return load_settings_safely(AppSettings)
