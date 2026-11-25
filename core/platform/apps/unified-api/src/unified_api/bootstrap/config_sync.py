"""Composition Root helpers wiring Universal Control-to-Data Plane Dynamic Watch."""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from config_sync.adapters.inbound.watch_auth_strategies import (
    AllowUnauthenticatedDevWatchAuthStrategy,
    BearerTokenWatchAuthStrategy,
    FailClosedUnconfiguredAuthStrategy,
)
from config_sync.application.stream_config_watch_use_case import StreamConfigWatchUseCase
from config_sync.gateway import create_config_watch_gateway_app
from config_sync.ports.config_catalog_provider_port import ConfigCatalogProviderPort
from config_sync.ports.config_changelog_port import ConfigChangelogRepositoryPort
from config_sync.ports.config_watch_auth_port import ConfigWatchAuthStrategyPort
from config_sync.provider import ConfigSyncProvider
from database.provider import DatabaseProvider
from edi.adapters.outbound.config_sync.edi_config_catalog_provider import EdiConfigCatalogProvider
from fastapi import FastAPI
from identity.domain.identity_context import PLATFORM_TENANT_ID
from ip.engine.adapters.outbound.config_sync.ip_config_catalog_provider import (
    IpConfigCatalogProvider,
)
from sqlalchemy.ext.asyncio import AsyncSession

from unified_api.settings import get_settings

SessionScopeFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

# Both IP wildcard ('*') and EDI shared platform tenant IDs must fan out to all tenant shards.
PLATFORM_SHARED_CONFIG_TENANT_IDS: tuple[str, ...] = ("*", PLATFORM_TENANT_ID)


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
    providers: list[ConfigCatalogProviderPort] = []
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


def build_config_watch_stream_use_case(
    *,
    session_factory: SessionScopeFactory,
    enabled_apps: str,
) -> StreamConfigWatchUseCase:
    """Builds a pure HTTP-ready `StreamConfigWatchUseCase` (zero background tasks)."""
    changelog_repo = ConfigSyncProvider.create_changelog_repository(
        session_factory=session_factory,
        shared_tenant_ids=PLATFORM_SHARED_CONFIG_TENANT_IDS,
    )
    providers = build_config_catalog_providers(
        session_factory=session_factory,
        changelog_repo=changelog_repo,
        enabled_apps=enabled_apps,
    )
    broadcaster = ConfigSyncProvider.create_broadcaster(
        broadcast_tenant_ids=PLATFORM_SHARED_CONFIG_TENANT_IDS,
    )
    return ConfigSyncProvider.create_stream_use_case(
        providers=providers,
        broadcaster=broadcaster,
    )


def create_watch_gateway_app(enabled_apps: str | None = None) -> FastAPI:
    """Creates the standalone Shopify-style Control Plane Config Watch Gateway ASGI app.

    Runs `PostgresNotifyConfigBroadcasterBridge` (`LISTEN config_sync_changelog`) inside
    this dedicated container so `unified-api` remains 100% pure stateless HTTP.
    """
    settings = get_settings()
    resolved_enabled = enabled_apps if enabled_apps is not None else settings.enabled_apps
    db_url = os.environ.get("DATABASE_URL") or str(settings.database.global_url)
    db_provider = DatabaseProvider.from_url(db_url)
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
    return create_config_watch_gateway_app(
        database_url=db_url,
        changelog_repo=changelog_repo,
        providers=providers,
        auth_strategy=auth_strategy,
        broadcaster=broadcaster,
        on_shutdown=db_provider.close,
    )


__all__ = [
    "PLATFORM_SHARED_CONFIG_TENANT_IDS",
    "build_config_catalog_providers",
    "build_config_watch_stream_use_case",
    "create_watch_gateway_app",
    "parse_enabled_app_names",
    "resolve_watch_auth_strategy",
]
