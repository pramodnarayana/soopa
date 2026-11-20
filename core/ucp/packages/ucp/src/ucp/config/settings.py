from functools import lru_cache

from identity import PlatformIdentitySettings
from pydantic import Field
from pydantic_settings import SettingsConfigDict
from seedwork.infra.config import CleanBaseSettings, load_settings_safely
from seedwork.infra.config_models import (
    PlatformAwsSettings,
    PlatformDatabaseSettings,
)


class UcpAwsSettings(PlatformAwsSettings):
    sns_tenant_events_topic_arn: str = Field(
        validation_alias="SNS_PLATFORM_EVENTS_TOPIC_ARN", default=""
    )


class SqsSettings(CleanBaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    ucp_identity_sync_queue_url: str = Field(
        validation_alias="SQS_UCP_IDENTITY_SYNC_QUEUE_URL", default=""
    )
    ucp_jobs_queue_url: str = Field(validation_alias="SQS_UCP_JOBS_QUEUE_URL", default="")


class AppSettings(CleanBaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    use_localstack: bool = Field(validation_alias="USE_LOCALSTACK", default=False)
    outbox_sweeper_batch_limit: int = Field(
        validation_alias="OUTBOX_SWEEPER_BATCH_LIMIT", default=100
    )
    outbox_sweeper_cron_interval: int = Field(
        validation_alias="OUTBOX_SWEEPER_CRON_INTERVAL", default=5
    )

    database: PlatformDatabaseSettings = Field(default_factory=PlatformDatabaseSettings)
    aws: UcpAwsSettings = Field(default_factory=UcpAwsSettings)
    sqs: SqsSettings = Field(default_factory=SqsSettings)
    identity: PlatformIdentitySettings = Field(default_factory=PlatformIdentitySettings)

    idp_api_url_value: str = Field(validation_alias="IDENTITY_API_URL", default="")
    idp_machine_key_value: str = Field(validation_alias="IDENTITY_MACHINE_KEY", default="")
    idp_default_user_password_value: str = Field(
        validation_alias="IDENTITY_DEFAULT_USER_PASSWORD", default=""
    )
    control_plane_project_id_value: str = Field(
        validation_alias="IDENTITY_UCP_PROJECT_ID",
        default="",
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
    def idp_api_url(self) -> str:
        return self.idp_api_url_value

    @property
    def idp_machine_key(self) -> str:
        return self.idp_machine_key_value

    @property
    def control_plane_project_id(self) -> str:
        return self.control_plane_project_id_value

    @property
    def idp_default_user_password(self) -> str:
        return self.idp_default_user_password_value


@lru_cache
def get_settings() -> AppSettings:
    return load_settings_safely(AppSettings)
