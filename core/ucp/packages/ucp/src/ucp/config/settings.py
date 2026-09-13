import typing
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from seedwork.infrastructure.config import load_settings_safely
from seedwork.infrastructure.config_models import (
    PlatformAwsSettings,
    PlatformDatabaseSettings,
    PlatformIdentitySettings,
)


class UcpAwsSettings(PlatformAwsSettings):
    sns_tenant_events_topic_arn: str = Field(
        validation_alias="SNS_TENANT_EVENTS_TOPIC_ARN", default=""
    )


class SqsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    ucp_identity_sync_queue_url: str = Field(
        validation_alias="SQS_UCP_IDENTITY_SYNC_QUEUE_URL", default=""
    )
    ucp_jobs_queue_url: str = Field(validation_alias="SQS_UCP_JOBS_QUEUE_URL", default="")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    use_localstack: bool = Field(validation_alias="USE_LOCALSTACK", default=False)
    outbox_sweeper_batch_limit: int = Field(
        validation_alias="OUTBOX_SWEEPER_BATCH_LIMIT", default=100
    )
    outbox_sweeper_cron_interval: int = Field(
        validation_alias="OUTBOX_SWEEPER_CRON_INTERVAL", default=5
    )

    database: PlatformDatabaseSettings = Field(
        default_factory=lambda: typing.cast(PlatformDatabaseSettings, {})
    )
    aws: UcpAwsSettings = Field(default_factory=lambda: typing.cast(UcpAwsSettings, {}))
    sqs: SqsSettings = Field(default_factory=lambda: typing.cast(SqsSettings, {}))
    identity: PlatformIdentitySettings = Field(
        default_factory=lambda: typing.cast(PlatformIdentitySettings, {})
    )

    @property
    def database_url(self) -> str:
        return self.database.global_url

    @property
    def aws_endpoint_url(self) -> str | None:
        return self.aws.endpoint_url

    @property
    def aws_region(self) -> str:
        return self.aws.resolved_region

    @property
    def aws_access_key_id(self) -> str | None:
        return self.aws.access_key_id

    @property
    def aws_secret_access_key(self) -> str | None:
        return self.aws.secret_access_key

    @property
    def sns_tenant_events_topic_arn(self) -> str:
        return self.aws.sns_tenant_events_topic_arn

    @property
    def sqs_ucp_identity_sync_queue_url(self) -> str:
        return self.sqs.ucp_identity_sync_queue_url

    @property
    def sqs_ucp_jobs_queue_url(self) -> str:
        return self.sqs.ucp_jobs_queue_url

    @property
    def zitadel_api_url(self) -> str:
        return self.identity.api_url

    @property
    def zitadel_machine_key(self) -> str:
        return self.identity.machine_key

    @property
    def zitadel_ucp_project_id(self) -> str:
        return self.identity.ucp_project_id

    @property
    def zitadel_tenant_role_group(self) -> str:
        return self.identity.tenant_role_group

    @property
    def zitadel_platform_org_id(self) -> str:
        return self.identity.platform_org_id

    @property
    def zitadel_issuer(self) -> str:
        return self.identity.issuer

    @property
    def zitadel_default_user_password(self) -> str:
        return self.identity.default_user_password


@lru_cache
def get_settings() -> AppSettings:
    return load_settings_safely(AppSettings)
