from functools import lru_cache

from identity.config import PlatformIdentitySettings
from pubsub.config import PlatformPubSubSettings
from pydantic import Field, computed_field, model_validator
from pydantic_settings import SettingsConfigDict
from seedwork.infra.config import CleanBaseSettings, load_settings_safely
from seedwork.infra.config_models import (
    PlatformAwsSettings,
    PlatformDatabaseSettings,
)


class IdentityAwsSettings(PlatformAwsSettings):
    sns_identity_events_topic_arn: str = Field(
        validation_alias="SNS_PLATFORM_EVENTS_TOPIC_ARN", default=""
    )


class PlatformIdentityProvisioningSettings(PlatformIdentitySettings):
    """
    Settings required for provisioning identity resources (used ONLY by Identity Worker).
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    platform_org_id: str = Field(
        validation_alias="IDENTITY_PLATFORM_ORG_ID",
        min_length=1,
        description="The primary platform organization ID.",
    )
    api_url: str = Field(
        validation_alias="IDENTITY_API_URL",
        description="The base URL of the IdP API.",
        default="",
    )
    machine_key: str = Field(
        validation_alias="IDENTITY_MACHINE_KEY",
        default="",
        description="JSON Service Account Key for authenticating as a machine user.",
    )
    default_user_password: str = Field(
        validation_alias="IDENTITY_DEFAULT_USER_PASSWORD",
        description="Default password for seeded/synced users.",
    )
    control_plane_project_id: str = Field(
        validation_alias="IDENTITY_UCP_PROJECT_ID",
        default="",
        description="The identity project defining platform tenant roles (e.g. TenantAdmin, TenantUser).",
    )


class SqsSettings(CleanBaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)
    identity_sync_queue_url: str = Field(validation_alias="SQS_IDENTITY_SYNC_QUEUE_URL", default="")


class AppSettings(CleanBaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    app_env: str = Field(validation_alias="ENV", default="production")

    database: PlatformDatabaseSettings = Field(default_factory=PlatformDatabaseSettings)
    aws: IdentityAwsSettings = Field(default_factory=IdentityAwsSettings)
    sqs: SqsSettings = Field(default_factory=SqsSettings)
    pubsub: PlatformPubSubSettings = Field(default_factory=PlatformPubSubSettings)
    identity: PlatformIdentityProvisioningSettings = Field(
        default_factory=PlatformIdentityProvisioningSettings
    )

    @model_validator(mode="after")
    def validate_pubsub_transport_uris(self) -> "AppSettings":
        self.pubsub.validate_uris(
            {
                "SNS_PLATFORM_EVENTS_TOPIC_ARN": self.aws.sns_identity_events_topic_arn,
                "SQS_IDENTITY_SYNC_QUEUE_URL": self.sqs.identity_sync_queue_url,
            }
        )
        return self

    @computed_field
    @property
    def database_url(self) -> str:
        return self.database.global_url

    @computed_field
    @property
    def sns_identity_events_topic_arn(self) -> str:
        return self.aws.sns_identity_events_topic_arn

    @computed_field
    @property
    def sqs_identity_sync_queue_url(self) -> str:
        return self.sqs.identity_sync_queue_url

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

    @computed_field
    @property
    def idp_api_url(self) -> str:
        return self.identity.api_url

    @computed_field
    @property
    def idp_machine_key(self) -> str:
        return self.identity.machine_key

    @computed_field
    @property
    def idp_default_user_password(self) -> str:
        return self.identity.default_user_password

    @computed_field
    @property
    def tenant_role_group(self) -> str:
        return self.identity.tenant_role_group

    @computed_field
    @property
    def platform_org_id(self) -> str:
        return self.identity.platform_org_id

    @computed_field
    @property
    def control_plane_project_id(self) -> str:
        return self.identity.control_plane_project_id


@lru_cache
def get_settings() -> AppSettings:
    return load_settings_safely(AppSettings)
