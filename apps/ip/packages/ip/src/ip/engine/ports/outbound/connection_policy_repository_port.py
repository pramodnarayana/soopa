"""Outbound port interface for persisting and reading ConnectionPolicy aggregates."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.connection.connection_policy import ConnectionPolicy


class ConnectionPolicyRepositoryPort(Protocol):
    """Port interface for ConnectionPolicy persistence in the Control Plane."""

    async def get_by_connection_id(
        self, tenant_id: str, connection_id: str
    ) -> ConnectionPolicy | None:
        """Retrieves operational policy for a specific connection, or None if unconfigured."""
        ...

    async def get_by_id(self, tenant_id: str, policy_id: str) -> ConnectionPolicy | None:
        """Retrieves operational policy by its primary key ID."""
        ...

    async def save(self, policy: ConnectionPolicy) -> None:
        """Persists or updates the ConnectionPolicy aggregate and drains its domain events."""
        ...

    async def delete(
        self,
        tenant_id: str,
        connection_id: str,
        policy: ConnectionPolicy | None = None,
    ) -> bool:
        """Deletes operational policy for a connection and drains domain events. Returns True if deleted."""
        ...
