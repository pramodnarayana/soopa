from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
    sns_identity_events_topic_arn: str = ""
    sqs_identity_sync_queue_url: str = ""
    aws_endpoint_url: str | None = None
    aws_region: str = "us-east-1"
    app_env: str = "production"
    zitadel_api_url: str = ""
    zitadel_api_token: str = ""
    zitadel_ucp_project_id: str = ""
    zitadel_default_user_password: str
    zitadel_tenant_role_group: str = "Tenant"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
