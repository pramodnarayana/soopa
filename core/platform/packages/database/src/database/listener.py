"""Centralized PostgreSQL LISTEN/NOTIFY Connection Provisioning."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import asyncpg

from database.utils import normalize_to_standard_postgres

NotifyCallback = Callable[[object, int, str, str], None]


class NotifyListenerConnectionPort(Protocol):
    """Abstract port for an active asynchronous LISTEN/NOTIFY database connection."""

    async def add_listener(self, channel: str, callback: NotifyCallback) -> None: ...

    async def remove_listener(self, channel: str, callback: NotifyCallback) -> None: ...

    async def close(self) -> None: ...

    def is_closed(self) -> bool: ...


async def connect_notify_listener(url: str) -> NotifyListenerConnectionPort:
    """Normalizes `url` and opens a dedicated asyncpg connection for LISTEN/NOTIFY."""
    normalized_url = normalize_to_standard_postgres(url)
    conn: NotifyListenerConnectionPort = await asyncpg.connect(normalized_url)
    return conn


__all__ = [
    "NotifyCallback",
    "NotifyListenerConnectionPort",
    "connect_notify_listener",
]
