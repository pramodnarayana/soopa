"""MappingBindingRepositoryPort for stream mapping configuration management."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.normalization import MappingBinding


class MappingBindingRepositoryPort(Protocol):
    """Port for persisting and retrieving stream-to-mapper bindings."""

    async def get_by_stream(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
    ) -> MappingBinding | None:
        """Retrieve active mapping binding for a tenant connection stream."""
        ...

    async def save(self, binding: MappingBinding) -> None:
        """Upsert a mapping binding configuration."""
        ...

    async def list_by_connection(
        self,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> list[MappingBinding]:
        """List all configured stream mapping bindings for a connection."""
        ...
