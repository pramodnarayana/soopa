"""
Shared application settings for all EDI AS2 services.
All settings are loaded from environment variables and validated by Pydantic.
Each service can use the full AppSettings or cherry-pick specific groups.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_", env_file=".env", extra="ignore")

    url: str = Field(
        default="postgresql+asyncpg://edi:edi_password@localhost/edi",
        description="Async PostgreSQL connection string.",
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


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["development", "staging", "production"] = Field(default="development")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    s3: S3Settings = Field(default_factory=S3Settings)
    otel: OtelSettings = Field(default_factory=OtelSettings)


@lru_cache
def get_settings() -> AppSettings:
    """
    Returns the cached application settings singleton.
    Decorated with @lru_cache so settings are only parsed once per process.
    """
    return AppSettings()
