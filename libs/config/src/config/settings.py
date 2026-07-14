"""
Shared application settings for all EDI AS2 services.
All settings are loaded from environment variables and validated by Pydantic.
Each service can use the full AppSettings or cherry-pick specific groups.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_", env_file=".env", extra="ignore")

    global_url: str = Field(
        validation_alias="DB_URL",
        serialization_alias="DB_GLOBAL_URL",
        default="postgresql+asyncpg://edi:edi_password@localhost:5432/edi_global",
        description="Async PostgreSQL connection string for the Global Control Plane.",
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
        default="http://localhost:8080/oauth/v2/authorize",
        description="The OAuth2 authorization endpoint URL",
    )
    token_url: str = Field(
        default="http://localhost:8080/oauth/v2/token",
        description="The OAuth2 token endpoint URL",
    )
    issuer: str = Field(
        default="http://localhost:8080",
        description="The OIDC Issuer URL",
    )
    jwks_url: str = Field(
        default="http://localhost:8080/oauth/v2/keys",
        description="The OIDC JWKS URL for verifying signatures",
    )
    userinfo_url: str = Field(
        default="http://localhost:8080/oidc/v1/userinfo",
        description="The OIDC UserInfo endpoint for remote token introspection",
    )
    audience: str = Field(
        default="api-gateway",
        description="The expected audience for the JWT",
    )


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SERVER_", env_file=".env", extra="ignore")

    external_url: str = Field(
        default="http://localhost:8000",
        description="The external base URL of the EDI platform",
    )


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["development", "staging", "production"] = Field(default="development")
    edi_environment: Literal["P", "T", "I"] = Field(
        default="P", description="EDI Environment flag (Production, Test, Information)"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    storage_backend: Literal["postgres", "s3"] = Field(default="postgres")

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    s3: S3Settings = Field(default_factory=S3Settings)
    otel: OtelSettings = Field(default_factory=OtelSettings)
    identity: IdentitySettings = Field(default_factory=IdentitySettings)
    server: ServerSettings = Field(default_factory=ServerSettings)

    @model_validator(mode="after")
    def validate_external_url(self) -> "AppSettings":
        import ipaddress
        from urllib.parse import urlparse

        if self.env != "development":
            if "://" not in self.server.external_url:
                raise ValueError("external_url must include a scheme (e.g. https://)")

            parsed = urlparse(self.server.external_url)
            host = parsed.hostname or ""

            if host == "localhost":
                raise ValueError(
                    "external_url must not be a loopback address in non-development environments"
                )

            try:
                ip = ipaddress.ip_address(host)
                if ip.is_loopback or ip.is_unspecified:
                    raise ValueError(
                        "external_url must not be a loopback address in non-development environments"
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
