"""Outbound Port for in-memory cyclic ring-buffer caching and real-time SSE fan-out."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from config_sync.domain.dtos import ConfigCursor, ConfigDeltaEvent


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
        since_cursor: ConfigCursor,
    ) -> list[ConfigDeltaEvent] | None:
        """Returns cached deltas newer than `since_cursor`, or `None` if `since_cursor` was evicted or incomplete."""
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
