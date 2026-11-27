"""Outbound Port for durable monotonically versioned configuration changelog storage."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from seedwork.domain.types import JsonDict

from config_sync.domain.dtos import (
    ChangelogVisibilityWatermark,
    ConfigCursor,
    ConfigDeltaEvent,
)
from config_sync.domain.enums import ConfigChangeAction


@runtime_checkable
class ConfigChangelogRepositoryPort(Protocol):
    """Stores append-only linearly ordered config deltas in PostgreSQL (`config_sync.config_changelog`)."""

    async def append_change(
        self,
        *,
        app_id: str,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        action: ConfigChangeAction,
        payload: JsonDict,
        event_id: str | None = None,
    ) -> ConfigDeltaEvent:
        """Atomically appends a change and assigns a monotonic `version` & `xid8` transaction id."""
        ...

    async def get_latest_cursor(self, *, app_id: str, tenant_id: str) -> ConfigCursor:
        """Returns the highest visibility-safe `(txid, version)` cursor for `(app_id, tenant_id)`."""
        ...

    async def get_global_safe_cursor(self) -> ConfigCursor:
        """Returns the highest globally visible `(txid, version)` cursor across all apps."""
        ...

    async def get_deltas_since(
        self,
        *,
        app_id: str,
        tenant_id: str,
        since_cursor: ConfigCursor,
        limit: int = 1000,
    ) -> list[ConfigDeltaEvent]:
        """Returns visibility-safe deltas with `(txid, version) > since_cursor` ordered by `(txid, version)`."""
        ...

    async def get_entries_after_cursor(
        self,
        *,
        since_cursor: ConfigCursor,
        limit: int = 1000,
    ) -> list[ConfigDeltaEvent]:
        """Returns global visibility-safe entries with `(txid, version) > since_cursor` for cursor tailing."""
        ...

    async def get_visibility_lag_metrics(self) -> ChangelogVisibilityWatermark:
        """Returns the visibility-safe head vs raw head cursor to detect long-running write stalls."""
        ...

    async def cleanup_old_entries(self, *, retention_days: int = 30) -> int:
        """Purges old changelog rows in bounded chunks with cooperative yielding."""
        ...


__all__ = ["ConfigChangelogRepositoryPort"]
