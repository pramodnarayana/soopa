"""Outbound Port implemented by each bounded context (`edi`, `ip`, `appX`) to serve Dynamic Watch catalogs."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from config_sync.domain.dtos import ConfigCursor, ConfigDeltaEvent, ConfigSnapshot


@runtime_checkable
class ConfigCatalogProviderPort(Protocol):
    """Domain-implemented provider supplying authoritative snapshots and incremental deltas for one app."""

    @property
    def app_id(self) -> str:
        """Logical application identifier (e.g. `'edi'`, `'ip'`)."""
        ...

    async def get_tenant_snapshot(self, *, tenant_id: str) -> ConfigSnapshot:
        """Returns the complete authoritative active configuration snapshot for `tenant_id`."""
        ...

    async def get_deltas_since(
        self, *, tenant_id: str, since_cursor: ConfigCursor
    ) -> list[ConfigDeltaEvent]:
        """Returns ordered incremental delta events strictly newer than `since_cursor`."""
        ...


__all__ = ["ConfigCatalogProviderPort"]
