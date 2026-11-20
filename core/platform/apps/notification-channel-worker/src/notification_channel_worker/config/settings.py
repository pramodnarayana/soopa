from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import SettingsConfigDict
from seedwork.infra.config import CleanBaseSettings, load_settings_safely
from seedwork.infra.config_models import (
    PlatformAwsSettings,
    PlatformDatabaseSettings,
)


class SqsSettings(CleanBaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)
    email_channel_queue_url: str = Field(
        validation_alias="SQS_EMAIL_CHANNEL_QUEUE_URL",
        default="",
        min_length=1,
    )


class AppSettings(CleanBaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    database: PlatformDatabaseSettings = Field(default_factory=lambda: PlatformDatabaseSettings())
    aws: PlatformAwsSettings = Field(default_factory=lambda: PlatformAwsSettings())
    sqs: SqsSettings = Field(default_factory=lambda: SqsSettings())

    @computed_field
    @property
    def database_url(self) -> str:
        return self.database.global_url

    @computed_field
    @property
    def sqs_email_channel_queue_url(self) -> str:
        return self.sqs.email_channel_queue_url

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
