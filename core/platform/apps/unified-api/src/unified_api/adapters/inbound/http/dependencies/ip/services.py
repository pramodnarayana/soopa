"""Service and adapter dependencies for Integration Platform HTTP routers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Annotated

from fastapi import Depends
from security.ports.cipher_port import CipherPort
from security.provider import SecurityProvider

from ip.application.connectors.registry_loader import create_default_catalog_registry
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import TieredStorageAdapter
from ip.engine.ports.outbound.catalog_registry_port import CatalogRegistryPort
from ip.engine.ports.outbound.connector_port import ConnectorPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
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


__all__ = [
    "get_catalog_registry",
    "get_cipher",
    "get_connectors",
    "get_tiered_storage",
]
