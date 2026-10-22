"""Port contract for storing and querying Layer 5 OutboundRecord audit records."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.models.outbound_record import OutboundRecord


class OutboundRecordRepositoryPort(Protocol):
    """Outbound repository port for Layer 5 raw outbound records."""

    @abstractmethod
    async def save(self, record: OutboundRecord) -> None:
        """Persists the outbound record into the partition-backed storage."""
        ...

    @abstractmethod
    async def get_by_id(self, record_id: str, tenant_id: str) -> OutboundRecord | None:
        """Retrieves an outbound record by primary key scoped to tenant."""
        ...

    @abstractmethod
    async def get_by_trace_id(
        self, trace_id: str, tenant_id: str
    ) -> Sequence[OutboundRecord]:
        """Retrieves all outbound records associated with a trace ID."""
        ...
