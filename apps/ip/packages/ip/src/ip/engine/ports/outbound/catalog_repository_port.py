"""Port protocol for the ConnectionCatalog aggregate repository."""

from abc import abstractmethod
from typing import Protocol

from ip.engine.domain.connection.catalog import ConnectionCatalog


class CatalogRepositoryPort(Protocol):
    """Hexagonal outbound port for persisting and querying ConnectionCatalog aggregates."""

    @abstractmethod
    async def save(self, catalog: ConnectionCatalog) -> None:
        """Persists a ConnectionCatalog aggregate."""
        ...

    @abstractmethod
    async def get_active_by_connection_id(
        self,
        tenant_id: str,
        connection_id: str,
    ) -> ConnectionCatalog | None:
        """Retrieves the active catalog schema for a tenant's connection."""
        ...

    @abstractmethod
    async def get_by_version(
        self,
        tenant_id: str,
        connection_id: str,
        version: int,
    ) -> ConnectionCatalog | None:
        """Retrieves a specific historical version of a tenant connection's catalog."""
        ...
