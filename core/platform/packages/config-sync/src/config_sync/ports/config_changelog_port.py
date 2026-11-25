"""Outbound Port for durable monotonically versioned configuration changelog storage."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from seedwork.domain.types import JsonDict

from config_sync.domain.dtos import ConfigDeltaEvent
from config_sync.domain.enums import ConfigChangeAction


@runtime_checkable
class ConfigChangelogRepositoryPort(Protocol):
    """Stores append-only monotonically versioned config deltas in PostgreSQL (`config_sync.config_changelog`)."""

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
        """Atomically appends a change, assigns a monotonic `version`, and emits `pg_notify`."""
        ...

    async def get_latest_version(self, *, app_id: str, tenant_id: str) -> int:
        """Returns the highest persisted version for `(app_id, tenant_id)` (including wildcard `*`)."""
        ...

    async def get_deltas_since(
        self,
        *,
        app_id: str,
        tenant_id: str,
        since_version: int,
        limit: int = 1000,
    ) -> list[ConfigDeltaEvent]:
        """Returns ordered deltas with `version > since_version` for catch-up streaming."""
        ...

    async def get_entry_by_version(self, *, version: int) -> ConfigDeltaEvent | None:
        """Fetches a single changelog entry by its monotonic version (used by LISTEN/NOTIFY bridge)."""
        ...

    async def get_entries_after_version(
        self,
        *,
        since_version: int,
        limit: int = 1000,
    ) -> list[ConfigDeltaEvent]:
        """Returns ordered global entries with `version > since_version` for LISTEN/NOTIFY reconnect catch-up."""
        ...

    async def cleanup_old_entries(self, *, retention_days: int = 30) -> int:
        """Purges old changelog rows in bounded chunks with cooperative yielding."""
        ...


__all__ = ["ConfigChangelogRepositoryPort"]
