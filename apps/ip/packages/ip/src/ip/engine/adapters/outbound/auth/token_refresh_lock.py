"""PostgreSQL advisory-lock and in-memory per-connection lock adapters for TokenRefreshLockPort."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from collections.abc import AsyncIterator

from database.router import DatabaseRouterPort
from ip.engine.ports.outbound.token_refresh_lock_port import TokenRefreshLockPort
from sqlalchemy import text


def compute_token_refresh_advisory_key(connection_id: str) -> int:
    """Computes a deterministic 64-bit signed integer PostgreSQL advisory lock key for a connection_id."""
    digest = hashlib.sha256(f"ip:token_refresh:{connection_id}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


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


class SqlAlchemyTokenRefreshLockAdapter(TokenRefreshLockPort):
    """Cross-container distributed lock adapter using PostgreSQL `pg_advisory_xact_lock` on Control Plane DB."""

    def __init__(self, db_router: DatabaseRouterPort | None = None) -> None:
        self._db_router = db_router
        self._local_locks: dict[str, asyncio.Lock] = {}

    def _get_local_lock(self, connection_id: str) -> asyncio.Lock:
        lock = self._local_locks.get(connection_id)
        if lock is None:
            lock = asyncio.Lock()
            self._local_locks[connection_id] = lock
        return lock

    @contextlib.asynccontextmanager
    async def acquire(self, connection_id: str) -> AsyncIterator[None]:
        local_lock = self._get_local_lock(connection_id)
        async with local_lock:
            if self._db_router is None:
                yield
                return

            lock_key = compute_token_refresh_advisory_key(connection_id)
            acquired = False
            async for session in self._db_router.get_global_session():
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": lock_key},
                )
                acquired = True
                try:
                    yield
                finally:
                    await session.commit()
                break

            if not acquired:
                yield


__all__ = [
    "InMemoryTokenRefreshLockAdapter",
    "SqlAlchemyTokenRefreshLockAdapter",
    "compute_token_refresh_advisory_key",
]
