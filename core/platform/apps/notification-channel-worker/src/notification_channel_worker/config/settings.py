from functools import lru_cache

from pubsub.config import PlatformPubSubSettings
from pydantic import Field, computed_field, model_validator
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
    pubsub: PlatformPubSubSettings = Field(default_factory=lambda: PlatformPubSubSettings())

    @model_validator(mode="after")
    def validate_pubsub_transport_uris(self) -> "AppSettings":
        self.pubsub.validate_uris({"SQS_EMAIL_CHANNEL_QUEUE_URL": self.sqs.email_channel_queue_url})
        return self

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
    def pubsub_transport(self) -> str | None:
        return self.pubsub.transport

    @computed_field
    @property
    def aws_endpoint_url(self) -> str | None:
        return self.pubsub.effective_aws_endpoint_url(self.aws.endpoint_url)

    @computed_field
    @property
    def aws_region(self) -> str:
        return self.aws.resolved_region


@lru_cache
def get_settings() -> AppSettings:
    return load_settings_safely(AppSettings)
