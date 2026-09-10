import typing
from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from seedwork.infrastructure.config import load_settings_safely
from seedwork.infrastructure.config_models import (
    PlatformAwsSettings,
    PlatformDatabaseSettings,
    PlatformIdentitySettings,
)


class IdentityAwsSettings(PlatformAwsSettings):
    sns_identity_events_topic_arn: str = Field(
        validation_alias="SNS_IDENTITY_EVENTS_TOPIC_ARN", default=""
    )


class SqsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    identity_sync_queue_url: str = Field(validation_alias="SQS_IDENTITY_SYNC_QUEUE_URL", default="")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_env: str = Field(validation_alias="ENV", default="production")

    database: PlatformDatabaseSettings = Field(
        default_factory=lambda: typing.cast(PlatformDatabaseSettings, {})
    )
    aws: IdentityAwsSettings = Field(default_factory=lambda: typing.cast(IdentityAwsSettings, {}))
    sqs: SqsSettings = Field(default_factory=lambda: typing.cast(SqsSettings, {}))
    identity: PlatformIdentitySettings = Field(
        default_factory=lambda: typing.cast(PlatformIdentitySettings, {})
    )

    @property
    @computed_field
    def database_url(self) -> str:
        return self.database.global_url

    @property
    @computed_field
    def sns_identity_events_topic_arn(self) -> str:
        return self.aws.sns_identity_events_topic_arn

    @property
    @computed_field
    def sqs_identity_sync_queue_url(self) -> str:
        return self.sqs.identity_sync_queue_url

    @property
    @computed_field
    def aws_endpoint_url(self) -> str | None:
        return self.aws.endpoint_url

    @property
    @computed_field
    def aws_region(self) -> str:
        return self.aws.resolved_region

    @property
    @computed_field
    def zitadel_api_url(self) -> str:
        return self.identity.api_url

    @property
    @computed_field
    def zitadel_machine_key(self) -> str:
        return self.identity.machine_key

    @property
    @computed_field
    def zitadel_ucp_project_id(self) -> str:
        return self.identity.ucp_project_id

    @property
    @computed_field
    def zitadel_default_user_password(self) -> str:
        return self.identity.default_user_password

    @property
    @computed_field
    def zitadel_tenant_role_group(self) -> str:
        return self.identity.tenant_role_group


@lru_cache
def get_settings() -> AppSettings:
    return load_settings_safely(AppSettings)
