"""Outbound port protocol for persisting and querying SyncRun aggregates."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.models.sync_run import SyncRun


class SyncRunRepositoryPort(Protocol):
    """Repository port interface for pull synchronization runs."""

    async def get_by_id(self, run_id: str, tenant_id: str) -> SyncRun | None:
        """Retrieves a sync run by its unique identifier and tenant."""
        ...

    async def get_active_run(
        self,
        connection_id: str,
        stream: str,
        tenant_id: str | None = None,
    ) -> SyncRun | None:
        """Retrieves the active (PENDING or RUNNING) sync run for a stream, if one exists."""
        ...

    async def get_latest_generation_id(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
    ) -> int:
        """Retrieves the highest generation_id recorded for a stream (defaults to 1)."""
        ...

    async def list_by_connection(
        self,
        tenant_id: str,
        connection_id: str,
        limit: int = 50,
    ) -> Sequence[SyncRun]:
        """Lists recent sync runs for a connection, ordered newest first."""
        ...

    async def save(self, run: SyncRun) -> None:
        """Persists or updates a sync run and drains its domain events."""
        ...
