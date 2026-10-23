"""Port contract for storing and querying Layer 3 NormalizedRecord entities."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.models.normalized_record import NormalizedRecord


class NormalizedRecordRepositoryPort(Protocol):
    """Outbound repository port for Layer 3 canonical normalized record audit entries."""

    @abstractmethod
    async def save(self, record: NormalizedRecord) -> None:
        """Persists the normalized record and drains trace/domain events into the outbox."""
        ...

    @abstractmethod
    async def get_by_id(self, record_id: str, tenant_id: str) -> NormalizedRecord | None:
        """Retrieves a normalized record by ID and tenant."""
        ...

    @abstractmethod
    async def list_by_source(
        self,
        tenant_id: str,
        canonical_type: str,
        source_id: str,
    ) -> Sequence[NormalizedRecord]:
        """Lists normalized audit records for a given canonical entity type and source ID."""
        ...
