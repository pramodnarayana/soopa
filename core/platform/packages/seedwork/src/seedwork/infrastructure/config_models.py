from database.utils import normalize_to_asyncpg
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformDatabaseSettings(BaseSettings):
    """
    Centralized model for Database connection pooling and routing.
    Provides standard attributes consumed by DatabaseRouter.
    """

    model_config = SettingsConfigDict(extra="ignore")

    global_url: str = Field(
        validation_alias="DATABASE_URL",
        serialization_alias="DATABASE_URL",
        description="Async PostgreSQL connection string for the Global Control Plane.",
    )
    pool_size: int = Field(validation_alias="DB_POOL_SIZE", default=10)
    max_overflow: int = Field(validation_alias="DB_MAX_OVERFLOW", default=20)

    @model_validator(mode="after")
    def force_asyncpg(self) -> "PlatformDatabaseSettings":
        if self.global_url:
            self.global_url = normalize_to_asyncpg(self.global_url)
        return self


class PlatformAwsSettings(BaseSettings):
    """
    Centralized model for AWS Credentials, Endpoints, and Regions.
    Used by SQS Polling, SNS Publishing, and S3 clients.
    """

    model_config = SettingsConfigDict(extra="ignore")

    endpoint_url: str | None = Field(validation_alias="AWS_ENDPOINT_URL", default=None)
    region: str | None = Field(validation_alias="AWS_REGION", default=None)
    default_region: str = Field(validation_alias="AWS_DEFAULT_REGION", default="us-east-1")
    access_key_id: str | None = Field(validation_alias="AWS_ACCESS_KEY_ID", default=None)
    secret_access_key: str | None = Field(validation_alias="AWS_SECRET_ACCESS_KEY", default=None)

    @property
    def resolved_region(self) -> str:
        return self.region or self.default_region


class PlatformOtelSettings(BaseSettings):
    """
    Centralized model for OpenTelemetry Configuration.
    """

    model_config = SettingsConfigDict(extra="ignore")

    service_name: str = Field(validation_alias="OTEL_SERVICE_NAME", default="soopa-worker")
    exporter_otlp_endpoint: str = Field(
        validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT",
        description="OTLP gRPC/HTTP endpoint of the OpenTelemetry Collector.",
        default="",
    )
    enabled: bool = Field(validation_alias="OTEL_ENABLED", default=True)


class PlatformIdentitySettings(BaseSettings):
    """
    Centralized model for Identity Provider Configuration (Zitadel).
    """

    model_config = SettingsConfigDict(extra="ignore")

    api_url: str = Field(
        validation_alias="ZITADEL_API_URL",
        description="The base URL of the Zitadel API.",
        default="",
    )
    machine_key: str = Field(
        validation_alias="ZITADEL_MACHINE_KEY",
        default="",
        description="JSON Service Account Key for authenticating as a machine user.",
    )
    ucp_project_id: str = Field(
        validation_alias="ZITADEL_UCP_PROJECT_ID",
        default="",
        description="The Project ID representing the UCP.",
    )
    default_user_password: str = Field(
        validation_alias="ZITADEL_DEFAULT_USER_PASSWORD",
        default="Password1!",
        description="Default password for seeded/synced users.",
    )
    tenant_role_group: str = Field(validation_alias="ZITADEL_TENANT_ROLE_GROUP", default="Tenant")
    platform_org_id: str = Field(validation_alias="ZITADEL_PLATFORM_ORG_ID", default="")
    issuer: str = Field(validation_alias="ZITADEL_ISSUER", default="")
    oauth_client_id: str = Field(validation_alias="ZITADEL_OAUTH_CLIENT_ID", default="")
