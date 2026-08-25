"""
Shared application settings for all EDI AS2 services.
All settings are loaded from environment variables and validated by Pydantic.
Each service can use the full AppSettings or cherry-pick specific groups.
"""

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_", env_file=".env", extra="ignore")

    global_url: str = Field(
        validation_alias="DB_GLOBAL_URL",
        serialization_alias="DB_GLOBAL_URL",
        default="postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global",
        description="Async PostgreSQL connection string for the Global Control Plane.",
    )
    default_shard_url: str | None = Field(
        validation_alias="SHARD_1_URL",
        default=None,
        description="Fallback shard URL used when UCP database_shards table is empty.",
    )
    pool_size: int = Field(default=10)
    max_overflow: int = Field(default=20)


class S3Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="S3_", env_file=".env", extra="ignore")

    bucket: str = Field(default="edi-as2-payloads")
    endpoint_url: str | None = Field(
        default=None,
        description="Override for MinIO or other S3-compatible stores. Leave empty for AWS S3.",
    )
    region: str = Field(default="us-east-1")
    access_key_id: str | None = Field(default=None)
    secret_access_key: str | None = Field(default=None)


class AwsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AWS_", env_file=".env", extra="ignore")

    endpoint_url: str | None = Field(default=None)
    region: str | None = Field(default=None)
    default_region: str = Field(default="us-east-1", validation_alias="AWS_DEFAULT_REGION")
    access_key_id: str | None = Field(default=None)
    secret_access_key: str | None = Field(default=None)
    sns_topic_arn: str = Field(default="")

    @property
    def resolved_region(self) -> str:
        return self.region or self.default_region


class OtelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OTEL_", env_file=".env", extra="ignore")

    service_name: str = Field(default="edi-as2-server")
    exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317",
        description="OTLP gRPC endpoint of the OpenTelemetry Collector.",
    )
    enabled: bool = Field(default=True)


class IdentitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IDENTITY_", env_file=".env", extra="ignore")

    oauth_client_id: str = Field(
        default="api-gateway",
        description="The ZITADEL Client ID for the API Gateway Swagger UI",
    )
    authorization_url: str = Field(
        default="http://ucp.localhost:8080/oauth/v2/authorize",
        description="The OAuth2 authorization endpoint URL",
    )
    token_url: str = Field(
        default="http://ucp.localhost:8080/oauth/v2/token",
        description="The OAuth2 token endpoint URL",
    )
    issuer: str = Field(
        default="http://ucp.localhost:8080",
        description="The OIDC Issuer URL",
    )
    jwks_url: str = Field(
        default="http://ucp.localhost:8080/oauth/v2/keys",
        description="The OIDC JWKS URL for verifying signatures",
    )
    userinfo_url: str = Field(
        default="http://ucp.localhost:8080/oidc/v1/userinfo",
        description="The OIDC UserInfo endpoint for remote token introspection",
    )
    audience: str | list[str] = Field(
        default="api-gateway",
        description="The expected audience for the JWT. Can be a single string or a comma-separated list of strings.",
    )

    @model_validator(mode="before")
    @classmethod
    def parse_audience(cls, data: Any) -> Any:
        if isinstance(data, dict) and "audience" in data:
            aud = data["audience"]
            if isinstance(aud, str) and "," in aud:
                data["audience"] = [a.strip() for a in aud.split(",") if a.strip()]
        return data


class PublicSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PUBLIC_", env_file=".env", extra="ignore")

    base_url: str = Field(
        default="http://localhost:3000",
        description="The external base URL of the EDI platform",
    )


from edi.config.constants import SECRETS_MOUNT_PATH


class SecretsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SECRETS_", env_file=".env", extra="ignore")

    mount_path: str = Field(default=SECRETS_MOUNT_PATH)
    sync_interval_seconds: int = Field(default=300)


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["development", "staging", "production"] = Field(default="development")
    enable_heavy_compute_queue: bool = Field(
        default=False,
        description="Feature flag to route heavy EDI parsing to a dedicated compute queue.",
    )
    edi_environment: Literal["P", "T", "I"] = Field(
        default="P", description="EDI Environment flag (Production, Test, Information)"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    storage_backend: Literal["postgres", "s3"] = Field(default="postgres")

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    s3: S3Settings = Field(default_factory=S3Settings)
    aws: AwsSettings = Field(default_factory=AwsSettings)
    otel: OtelSettings = Field(default_factory=OtelSettings)
    identity: IdentitySettings = Field(default_factory=IdentitySettings)
    public: PublicSettings = Field(default_factory=PublicSettings)
    secrets: SecretsSettings = Field(default_factory=SecretsSettings)

    @model_validator(mode="after")
    def validate_external_url(self) -> "AppSettings":
        import ipaddress
        from urllib.parse import urlparse

        if self.env != "development":
            if "://" not in self.public.base_url:
                raise ValueError("base_url must include a scheme (e.g. https://)")

            parsed = urlparse(self.public.base_url)
            host = parsed.hostname or ""

            if host == "localhost":
                raise ValueError(
                    "base_url must not be a loopback address in non-development environments"
                )

            try:
                ip = ipaddress.ip_address(host)
                if ip.is_loopback or ip.is_unspecified:
                    raise ValueError(
                        "base_url must not be a loopback address in non-development environments"
                    )
            except ValueError:
                pass

        return self


@lru_cache
def get_settings() -> AppSettings:
    """
    Returns the cached application settings singleton.
    Decorated with @lru_cache so settings are only parsed once per process.
    """
    return AppSettings()
