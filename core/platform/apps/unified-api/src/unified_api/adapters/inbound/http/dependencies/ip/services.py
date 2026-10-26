"""Service and adapter dependencies for Integration Platform HTTP routers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Annotated

from fastapi import Depends, Request
from security.ports.cipher_port import CipherPort
from security.provider import SecurityProvider

from ip.application.connectors.registry_loader import create_default_catalog_registry
from ip.engine.adapters.outbound.auth.oauth2_strategy import OAuth2StrategyTokenRefresher
from ip.engine.adapters.outbound.auth.token_refresh_lock import (
    InMemoryTokenRefreshLockAdapter,
)
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import TieredStorageAdapter
from ip.engine.application.use_cases.connections.token_manager_service import (
    TokenManagerService,
)
from ip.engine.ports.outbound.catalog_registry_port import CatalogRegistryPort
from ip.engine.ports.outbound.connector_port import ConnectorPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from unified_api.adapters.inbound.http.dependencies.ip.database import (
    get_ip_control_plane_uow,
)
from unified_api.settings import get_settings


class _ConnectorCatalogMapping(Mapping[str, ConnectorPort]):
    """Read-only Mapping adapter over CatalogRegistryPort."""

    def __init__(self, registry: CatalogRegistryPort) -> None:
        self._registry = registry

    def __getitem__(self, key: str) -> ConnectorPort:
        result = self._registry.get_connector(key)
        if result.is_ok and result.value is not None:
            return result.value
        raise KeyError(key)

    def __len__(self) -> int:
        return len(self._registry.list_apps())

    def __iter__(self) -> Iterator[str]:
        return (app.app_id for app in self._registry.list_apps())


def get_catalog_registry() -> CatalogRegistryPort:
    """Resolves a CatalogRegistryPort configured according to application settings."""
    settings = get_settings()
    return create_default_catalog_registry(allow_private_ips=settings.allow_private_ips)


def get_connectors(
    registry: Annotated[CatalogRegistryPort, Depends(get_catalog_registry)],
) -> Mapping[str, ConnectorPort]:
    """Resolves a Mapping[str, ConnectorPort] backed by CatalogRegistryPort."""
    return _ConnectorCatalogMapping(registry)


def get_cipher() -> CipherPort:
    """Resolves the platform CipherPort."""
    return SecurityProvider.get_cipher()


def get_tiered_storage() -> TieredStoragePort:
    """Resolves the TieredStoragePort backed by platform S3 PayloadStoragePort."""
    return TieredStorageAdapter()


def get_token_refresh_lock(request: Request) -> InMemoryTokenRefreshLockAdapter:
    """Resolves the in-memory token refresh lock adapter from application state."""
    state = request.app.state
    if not hasattr(state, "ip_token_refresh_lock") or state.ip_token_refresh_lock is None:
        state.ip_token_refresh_lock = InMemoryTokenRefreshLockAdapter()
    lock = state.ip_token_refresh_lock
    assert isinstance(lock, InMemoryTokenRefreshLockAdapter)
    return lock


def get_token_refresher(request: Request) -> OAuth2StrategyTokenRefresher:
    """Resolves the OAuth2StrategyTokenRefresher configured with app settings from application state."""
    state = request.app.state
    if not hasattr(state, "ip_token_refresher") or state.ip_token_refresher is None:
        settings = get_settings()
        state.ip_token_refresher = OAuth2StrategyTokenRefresher(
            allow_private_ips=settings.allow_private_ips
        )
    refresher = state.ip_token_refresher
    assert isinstance(refresher, OAuth2StrategyTokenRefresher)
    return refresher


def get_token_manager(
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    cipher: Annotated[CipherPort, Depends(get_cipher)],
    token_refresher: Annotated[OAuth2StrategyTokenRefresher, Depends(get_token_refresher)],
    lock_port: Annotated[InMemoryTokenRefreshLockAdapter, Depends(get_token_refresh_lock)],
) -> TokenManagerService:
    """Resolves the configured TokenManagerService for OAuth2 token freshness across IP operations."""
    return TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        token_refresher=token_refresher,
        lock_port=lock_port,
    )


__all__ = [
    "get_catalog_registry",
    "get_cipher",
    "get_connectors",
    "get_tiered_storage",
    "get_token_manager",
    "get_token_refresh_lock",
    "get_token_refresher",
]
