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
    identity_jobs_queue_url: str = Field(validation_alias="SQS_IDENTITY_JOBS_QUEUE_URL", default="")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database: PlatformDatabaseSettings = Field(
        default_factory=lambda: typing.cast(PlatformDatabaseSettings, {})
    )
    aws: PlatformAwsSettings = Field(default_factory=lambda: typing.cast(PlatformAwsSettings, {}))
    sqs: SqsSettings = Field(default_factory=lambda: typing.cast(SqsSettings, {}))

    @property
    @computed_field
    def database_url(self) -> str:
        return self.database.global_url

    @property
    @computed_field
    def sqs_identity_jobs_queue_url(self) -> str:
        return self.sqs.identity_jobs_queue_url

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
