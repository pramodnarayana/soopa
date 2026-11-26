"""Inbound/Outbound Transport Port for Data Plane Dynamic Watch streaming clients."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from seedwork.domain.exceptions import Result

from config_sync.domain.dtos import (
    ConfigCursor,
    ConfigDeltaEvent,
    ConfigSnapshot,
    ConfigSyncError,
    ConfigWatchHeartbeat,
)

WatchStreamItem = ConfigSnapshot | ConfigDeltaEvent | ConfigWatchHeartbeat | ConfigSyncError


@runtime_checkable
class ConfigWatchClientPort(Protocol):
    """Data Plane streaming client opening an outbound HTTPS/SSE watch stream to the Control Plane."""

    async def fetch_snapshot(
        self,
        *,
        app_id: str,
        tenant_id: str,
    ) -> Result[ConfigSnapshot, ConfigSyncError]:
        """Fetches an authoritative snapshot returning a first-class Result (never raising for HTTP errors)."""
        ...

    def watch(
        self,
        *,
        app_id: str,
        tenant_id: str,
        since_cursor: ConfigCursor | None = None,
    ) -> AsyncIterator[WatchStreamItem]:
        """Yields assembled `ConfigSnapshot`, live `ConfigDeltaEvent`, `ConfigWatchHeartbeat`, or `ConfigSyncError`."""
        ...


__all__ = ["ConfigWatchClientPort", "WatchStreamItem"]
