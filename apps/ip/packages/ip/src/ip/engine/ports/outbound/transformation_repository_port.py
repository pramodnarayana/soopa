"""TransformationRepositoryPort for stream transformation configuration management."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.normalization import Transformation


class TransformationRepositoryPort(Protocol):
    """Port for persisting and retrieving stream transformation configurations."""

    async def get_by_stream(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
    ) -> Transformation | None:
        """Retrieve active transformation for a tenant connection stream."""
        ...

    async def save(self, transformation: Transformation) -> None:
        """Upsert a transformation configuration."""
        ...

    async def list_by_connection(
        self,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> list[Transformation]:
        """List all configured stream transformations for a connection."""
        ...
