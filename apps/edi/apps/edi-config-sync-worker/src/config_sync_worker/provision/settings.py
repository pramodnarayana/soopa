"""Settings for the Queue-Free EDI Dynamic Watch Config Sync Worker."""

from __future__ import annotations

from functools import lru_cache

from edi.config.models import CommonSettings
from pydantic import AliasChoices, Field
from seedwork.infra.config import load_settings_safely


class WorkerSettings(CommonSettings):
    """Pure Dynamic Watch configuration (zero SQS/AWS/S3 dependencies)."""

    config_watch_base_url: str = Field(
        validation_alias=AliasChoices("EDI_CONFIG_WATCH_BASE_URL", "CONFIG_WATCH_BASE_URL"),
        default="http://localhost:8081",
    )
    config_watch_token: str = Field(
        validation_alias="CONFIG_SYNC_INTERNAL_TOKEN",
        default="",
    )
    config_watch_tenant_discovery_seconds: float = Field(
        validation_alias="CONFIG_WATCH_TENANT_DISCOVERY_SECONDS",
        default=30.0,
    )


@lru_cache
def get_settings() -> WorkerSettings:
    return load_settings_safely(WorkerSettings)


__all__ = ["WorkerSettings", "get_settings"]
