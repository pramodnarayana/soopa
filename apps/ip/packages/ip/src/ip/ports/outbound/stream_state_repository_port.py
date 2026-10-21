"""Outbound port protocol for persisting connection stream states."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ip.domain.models.stream_state import ConnectionStreamState


class StreamStateRepositoryPort(Protocol):
    """Repository port interface for incremental stream state checkpoints."""

    async def get_by_stream(
        self,
        tenant_id: str,
        connection_id: str,
        stream_name: str,
    ) -> ConnectionStreamState | None:
        """Retrieves stream state for a specific connection and stream."""
        ...

    async def list_by_connection(
        self,
        tenant_id: str,
        connection_id: str,
    ) -> Sequence[ConnectionStreamState]:
        """Lists all stream states recorded for a connection."""
        ...

    async def save(self, state: ConnectionStreamState) -> None:
        """Persists or updates stream state and flushes domain events."""
        ...
