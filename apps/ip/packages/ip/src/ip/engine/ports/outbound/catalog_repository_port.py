"""Port protocol for the ConnectionCatalog aggregate repository."""

from abc import abstractmethod
from typing import Protocol

from ip.engine.domain.models.catalog import ConnectionCatalog


class CatalogRepositoryPort(Protocol):
    """Hexagonal outbound port for persisting and querying ConnectionCatalog aggregates."""

    @abstractmethod
    async def save(self, catalog: ConnectionCatalog) -> None:
        """Persists a ConnectionCatalog aggregate."""
        ...

    @abstractmethod
    async def get_active_by_connection_id(
        self,
        connection_id: str,
    ) -> ConnectionCatalog | None:
        """Retrieves the active catalog schema for a given connection."""
        ...

    @abstractmethod
    async def get_by_version(
        self,
        connection_id: str,
        version: int,
    ) -> ConnectionCatalog | None:
        """Retrieves a specific historical version of a connection's catalog."""
        ...
