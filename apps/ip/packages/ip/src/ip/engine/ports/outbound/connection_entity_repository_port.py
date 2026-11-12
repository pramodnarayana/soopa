"""Port protocol for the ConnectionEntity aggregate repository."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.replication.connection_entity import ConnectionEntity


class ConnectionEntityRepositoryPort(Protocol):
    """Hexagonal outbound port for persisting and querying subscribed ConnectionEntity aggregates."""

    async def get_by_stream(
        self,
        tenant_id: str,
        connection_id: str,
        stream_name: str,
    ) -> ConnectionEntity | None:
        """Retrieves a subscribed entity on a connection by stream name."""
        ...

    async def list_by_connection(
        self,
        tenant_id: str,
        connection_id: str,
    ) -> Sequence[ConnectionEntity]:
        """Lists all subscribed entities configured for a connection ordered by stream name."""
        ...

    async def save(self, entity: ConnectionEntity) -> None:
        """Inserts or updates a ConnectionEntity aggregate and drains domain events."""
        ...

    async def delete(self, entity: ConnectionEntity) -> None:
        """Deletes a subscribed ConnectionEntity aggregate."""
        ...


__all__ = ["ConnectionEntityRepositoryPort"]
