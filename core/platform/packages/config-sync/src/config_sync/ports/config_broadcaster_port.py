"""Outbound Port for in-memory cyclic ring-buffer caching and real-time SSE fan-out."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from config_sync.domain.dtos import ConfigDeltaEvent


@runtime_checkable
class ConfigBroadcasterPort(Protocol):
    """Broadcasts committed `ConfigDeltaEvent`s to active watch streams and buffers recent deltas."""

    async def publish_delta(self, event: ConfigDeltaEvent) -> None:
        """Appends `event` to the per-(app, tenant) ring buffer and fans out to live subscribers."""
        ...

    def get_buffered_deltas_since(
        self,
        *,
        app_id: str,
        tenant_id: str,
        since_version: int,
    ) -> list[ConfigDeltaEvent] | None:
        """Returns cached deltas newer than `since_version`, or `None` if `since_version` was evicted."""
        ...

    def subscribe(
        self,
        *,
        app_id: str,
        tenant_id: str,
    ) -> AbstractAsyncContextManager[AsyncIterator[ConfigDeltaEvent]]:
        """Opens a bounded real-time async stream of live deltas for `(app_id, tenant_id)`."""
        ...


__all__ = ["ConfigBroadcasterPort"]
