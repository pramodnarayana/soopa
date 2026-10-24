"""Port protocol for the Connection aggregate repository."""

from abc import abstractmethod
from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.exceptions import DuplicateConnectionFingerprintError, Result
from ip.engine.domain.models.connection import Connection, ConnectionStatus


class ConnectionRepositoryPort(Protocol):
    """Hexagonal outbound port for persisting and querying Connection aggregates."""

    @abstractmethod
    async def save(
        self, connection: Connection
    ) -> Result[Connection, DuplicateConnectionFingerprintError]:
        """Persists a Connection aggregate and flushes pending domain events."""
        ...

    @abstractmethod
    async def get_by_id(self, connection_id: str) -> Connection | None:
        """Retrieves a Connection aggregate by its unique ID."""
        ...

    @abstractmethod
    async def get_by_fingerprint(
        self,
        tenant_id: str,
        fingerprint: str,
    ) -> Connection | None:
        """Retrieves a connection by tenant and external endpoint fingerprint."""
        ...

    @abstractmethod
    async def list_by_tenant(
        self,
        tenant_id: str,
        status: ConnectionStatus | None = None,
    ) -> Sequence[Connection]:
        """Lists all connections belonging to a tenant, optionally filtered by status."""
        ...
