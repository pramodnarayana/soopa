from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # AWS / SNS
    sns_tenant_events_topic_arn: str = ""
    sqs_ucp_identity_sync_queue_name: str = ""
    aws_endpoint_url: str | None = None
    aws_region: str = "us-east-1"
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"  # noqa: S105
    use_localstack: bool = False

    # Daemon / Sweep
    outbox_sweeper_batch_limit: int = 100
    outbox_sweeper_cron_interval: int = 5

    # Zitadel Identity Provider
    zitadel_api_url: str = "http://ucp.localhost:8080"
    zitadel_api_token: str = "test"  # noqa: S105
    zitadel_ucp_project_id: str = "test"
    zitadel_tenant_role_group: str = "Tenant"
    zitadel_platform_org_id: str = "test"
    # The OIDC issuer URL is used by the token verifier to fetch JWKS and validate JWTs.
    # For Zitadel this is the same as the API URL (e.g. http://ucp.localhost:8080).
    zitadel_issuer: str = "http://ucp.localhost:8080"
    # Default password for newly created users (local dev only - users must change on first login)
    zitadel_default_user_password: str = "Password1!"  # noqa: S105

    # Database
    database_url: str = ""

    @field_validator("database_url")
    @classmethod
    def inject_asyncpg_driver(cls, v: str) -> str:
        if v and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
