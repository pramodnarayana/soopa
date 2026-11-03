"""Inbound Outbox Relay lifecycle port."""

from __future__ import annotations

import asyncio
from typing import Protocol


class OutboxRelayPort(Protocol):
    """Port for background outbox relay lifecycle management."""

    def start(self) -> None: ...

    async def stop(self) -> None: ...

    def background_tasks(self) -> list[asyncio.Task[object]]: ...


__all__ = ["OutboxRelayPort"]
