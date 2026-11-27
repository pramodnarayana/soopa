"""Outbound Pluggable Sink Port for applying snapshots and deltas on Data Plane shards."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from config_sync.domain.dtos import (
    ConfigCursor,
    ConfigDeltaEvent,
    ConfigEntityRecord,
    ConfigSnapshot,
)


@runtime_checkable
class ConfigApplySinkPort(Protocol):
    """Data Plane sink consuming verified Dynamic Watch snapshots and deltas (in-memory, LKG disk, or shard DB)."""

    async def get_current_cursor(self, *, app_id: str, tenant_id: str) -> ConfigCursor:
        """Returns the last durably applied `(txid, version)` cursor on this Data Plane shard."""
        ...

    async def apply_snapshot(self, snapshot: ConfigSnapshot) -> None:
        """Atomically applies an authoritative full baseline snapshot."""
        ...

    async def apply_delta(self, delta: ConfigDeltaEvent) -> None:
        """Atomically applies a single monotonic delta mutation."""
        ...


@runtime_checkable
class ReadableConfigSinkPort(ConfigApplySinkPort, Protocol):
    """ConfigApplySinkPort extension exposing lock-free read snapshots for downstream domain projections."""

    @property
    def current_cursor(self) -> ConfigCursor:
        """Last durably applied monotonic `(txid, version)` cursor in this sink."""
        ...

    @property
    def current_version(self) -> int:
        """Last durably applied monotonic version in this sink."""
        ...

    def list_by_type(self, entity_type: str) -> tuple[ConfigEntityRecord, ...]:
        """Returns all active entities of `entity_type` from the current atomic snapshot."""
        ...


__all__ = ["ConfigApplySinkPort", "ReadableConfigSinkPort"]
