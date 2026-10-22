"""Port contract for storing and querying Layer 2 ReplicaRecord entities."""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from ip.engine.domain.models.replica_record import ReplicaRecord


class ReplicaRecordRepositoryPort(Protocol):
    """Outbound repository port for Layer 2 universal replica snapshots."""

    @abstractmethod
    async def save(self, record: ReplicaRecord) -> None:
        """Persists or updates the replica snapshot and flushes domain events."""
        ...

    @abstractmethod
    async def get_by_entity(
        self,
        tenant_id: str,
        connection_id: str,
        entity_type: str,
        entity_id: str,
    ) -> ReplicaRecord | None:
        """Retrieves an existing replica snapshot by composite entity key."""
        ...
