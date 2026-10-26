"""Port contract for persisting Layer 2 extraction and merge rejections."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.models.replica_record import ReplicaRejection


class ReplicaRejectionRepositoryPort(Protocol):
    """Outbound repository port for persisting rejected records at Layer 2."""

    @abstractmethod
    async def save_batch(self, rejections: Sequence[ReplicaRejection]) -> None:
        """Persists a batch of rejected records into the replica_rejections audit table."""
        ...

    async def get_by_trace_id(
        self,
        trace_id: str,
        tenant_id: str,
    ) -> Sequence[ReplicaRejection]:
        """Retrieves all replica rejections associated with a trace ID."""
        return ()
