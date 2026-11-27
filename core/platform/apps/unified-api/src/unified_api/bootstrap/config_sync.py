"""Composition Root helpers wiring Universal Control-to-Data Plane Dynamic Watch."""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Literal

from config_sync.adapters.inbound.watch_auth_strategies import (
    AllowUnauthenticatedDevWatchAuthStrategy,
    BearerTokenWatchAuthStrategy,
    FailClosedUnconfiguredAuthStrategy,
)
from config_sync.gateway import create_config_watch_gateway_app
from config_sync.ports.config_catalog_provider_port import ConfigCatalogProviderPort
from config_sync.ports.config_changelog_port import ConfigChangelogRepositoryPort
from config_sync.ports.config_watch_auth_port import ConfigWatchAuthStrategyPort
from config_sync.provider import ConfigSyncProvider
from database.config_changelog import CONTROL_PLANE_OLTP_SERVER_SETTINGS
from database.provider import DatabaseProvider
from edi.adapters.outbound.config_sync.edi_config_catalog_provider import EdiConfigCatalogProvider
from fastapi import FastAPI
from identity.adapters.outbound.config_sync.identity_config_catalog_provider import (
    IdentityConfigCatalogProvider,
)
from identity.domain.identity_context import PLATFORM_TENANT_ID
from ip.engine.adapters.outbound.config_sync.ip_config_catalog_provider import (
    IpConfigCatalogProvider,
)
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import SettingsConfigDict
from seedwork.infra.config import CleanBaseSettings, load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings
from sqlalchemy.ext.asyncio import AsyncSession

from unified_api.bootstrap.observability import setup_observability
from unified_api.settings import normalize_env_alias

SessionScopeFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

# Single canonical platform sentinel tenant shared across all tenants (zero dual `*` sentinel).
PLATFORM_SHARED_CONFIG_TENANT_IDS: tuple[str, ...] = (PLATFORM_TENANT_ID,)


class WatchGatewaySettings(CleanBaseSettings):
    """Minimal self-contained settings for the standalone `config-watch-gateway` container.

    Decouples the Watch Gateway from web-only API requirements such as `CORS_ALLOWED_ORIGINS`
    and OIDC configuration so it boots cleanly on ECS Fargate, Kubernetes, and on-prem.
    """

    model_config = SettingsConfigDict(extra="ignore")

    env: Literal["development", "staging", "production"] = Field(
        validation_alias=AliasChoices("ENV", "ENVIRONMENT"), default="development"
    )

    @field_validator("env", mode="before")
    @classmethod
    def _normalize_env_alias(cls, value: object) -> object:
        return normalize_env_alias(value)

    database: PlatformDatabaseSettings = Field(default_factory=PlatformDatabaseSettings)
    enabled_apps: str = Field(
        default="edi,ip",
        validation_alias="ENABLED_APPS",
    )
    config_sync_internal_token: str = Field(
        default="",
        validation_alias="CONFIG_SYNC_INTERNAL_TOKEN",
    )
    poll_interval_seconds: float = Field(
        default=0.15,
        validation_alias="CONFIG_WATCH_POLL_INTERVAL_SECONDS",
    )
    batch_size: int = Field(
        default=500,
        validation_alias="CONFIG_WATCH_BATCH_SIZE",
    )


def parse_enabled_app_names(enabled_apps: str) -> set[str]:
    """Parses comma-separated `ENABLED_APPS` string into normalized app names."""
    return {item.strip().lower() for item in enabled_apps.split(",") if item.strip()}


def resolve_watch_auth_strategy(
    *,
    internal_token: str,
    env: str,
) -> ConfigWatchAuthStrategyPort:
    """Selects fail-closed Bearer auth in all environments, permitting anonymous access only in local dev."""
    cleaned = internal_token.strip()
    if cleaned:
        return BearerTokenWatchAuthStrategy(cleaned)
    if env == "development":
        return AllowUnauthenticatedDevWatchAuthStrategy()
    return FailClosedUnconfiguredAuthStrategy()


def build_config_catalog_providers(
    *,
    session_factory: SessionScopeFactory,
    changelog_repo: ConfigChangelogRepositoryPort,
    enabled_apps: str,
) -> list[ConfigCatalogProviderPort]:
    """Assembles `ConfigCatalogProviderPort` adapters for all enabled bounded contexts."""
    enabled = parse_enabled_app_names(enabled_apps)
    providers: list[ConfigCatalogProviderPort] = [
        IdentityConfigCatalogProvider(
            session_factory=session_factory,
            changelog_repo=changelog_repo,
        )
    ]
    if "edi" in enabled:
        providers.append(
            EdiConfigCatalogProvider(
                session_factory=session_factory,
                changelog_repo=changelog_repo,
            )
        )
    if "ip" in enabled:
        providers.append(
            IpConfigCatalogProvider(
                session_factory=session_factory,
                changelog_repo=changelog_repo,
            )
        )
    return providers


def create_watch_gateway_app(enabled_apps: str | None = None) -> FastAPI:
    """Creates the standalone Shopify-style Control Plane Config Watch Gateway ASGI app.

    Sole canonical owner of `/api/v1/internal/*/config/*` in every environment.
    Runs `ChangelogCursorBroadcasterBridge` (linearizable `(txid, version)` Drain-Until-Empty
    tailer) inside this dedicated container so `unified-api` remains 100% pure stateless HTTP.
    """
    settings = load_settings_safely(WatchGatewaySettings)
    resolved_enabled = enabled_apps if enabled_apps is not None else settings.enabled_apps
    db_url = os.environ.get("DATABASE_URL") or str(settings.database.global_url)
    db_provider = DatabaseProvider.from_url(
        db_url,
        server_settings=CONTROL_PLANE_OLTP_SERVER_SETTINGS,
    )
    changelog_repo = ConfigSyncProvider.create_changelog_repository(
        session_factory=db_provider.session,
        shared_tenant_ids=PLATFORM_SHARED_CONFIG_TENANT_IDS,
    )
    broadcaster = ConfigSyncProvider.create_broadcaster(
        broadcast_tenant_ids=PLATFORM_SHARED_CONFIG_TENANT_IDS,
    )
    providers = build_config_catalog_providers(
        session_factory=db_provider.session,
        changelog_repo=changelog_repo,
        enabled_apps=resolved_enabled,
    )
    auth_strategy = resolve_watch_auth_strategy(
        internal_token=settings.config_sync_internal_token,
        env=settings.env,
    )
    app = create_config_watch_gateway_app(
        changelog_repo=changelog_repo,
        providers=providers,
        auth_strategy=auth_strategy,
        broadcaster=broadcaster,
        poll_interval_seconds=settings.poll_interval_seconds,
        batch_size=settings.batch_size,
        on_shutdown=db_provider.close,
    )
    setup_observability(app, service_name="soopa-config-watch-gateway")
    return app


__all__ = [
    "PLATFORM_SHARED_CONFIG_TENANT_IDS",
    "WatchGatewaySettings",
    "build_config_catalog_providers",
    "create_watch_gateway_app",
    "parse_enabled_app_names",
    "resolve_watch_auth_strategy",
]
