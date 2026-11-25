"""Application-layer registry mapping logical app_ids to bounded-context ConfigCatalogProviderPort instances."""

from __future__ import annotations

from collections.abc import Iterable

from seedwork.domain.exceptions import Result

from config_sync.domain.dtos import ConfigSyncError
from config_sync.domain.enums import ConfigSyncErrorCode
from config_sync.ports.config_catalog_provider_port import ConfigCatalogProviderPort


class ConfigCatalogRegistry:
    """Domain-agnostic registry populated via Inversion of Control by enabled bounded contexts."""

    def __init__(self, providers: Iterable[ConfigCatalogProviderPort] = ()) -> None:
        self._providers: dict[str, ConfigCatalogProviderPort] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: ConfigCatalogProviderPort) -> None:
        normalized = provider.app_id.strip().lower()
        if not normalized:
            raise ValueError("ConfigCatalogProviderPort.app_id must be a non-empty identifier.")
        self._providers[normalized] = provider

    def resolve(self, app_id: str) -> Result[ConfigCatalogProviderPort, ConfigSyncError]:
        normalized = app_id.strip().lower()
        provider = self._providers.get(normalized)
        if provider is None:
            return Result.fail(
                ConfigSyncError(
                    code=ConfigSyncErrorCode.UNKNOWN_APP,
                    message=f"No config catalog provider registered for app_id '{app_id}'.",
                )
            )
        return Result.ok(provider)

    def list_app_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers.keys()))


__all__ = ["ConfigCatalogRegistry"]
