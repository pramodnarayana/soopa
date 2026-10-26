"""In-memory per-connection async lock adapter for TokenRefreshLockPort."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from ip.engine.ports.outbound.token_refresh_lock_port import TokenRefreshLockPort


class InMemoryTokenRefreshLockAdapter(TokenRefreshLockPort):
    """Per-connection asyncio.Lock coordinator for single-process & unit-tested token refresh."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    @contextlib.asynccontextmanager
    async def acquire(self, connection_id: str) -> AsyncIterator[None]:
        lock = self._locks.get(connection_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[connection_id] = lock
        async with lock:
            yield


__all__ = ["InMemoryTokenRefreshLockAdapter"]
