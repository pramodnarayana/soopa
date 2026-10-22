"""Port contract for storing and querying Layer 1 InboundRecord audit records."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.models.inbound_record import InboundRecord


class InboundRecordRepositoryPort(Protocol):
    """Outbound repository port for Layer 1 raw inbound records."""

    @abstractmethod
    async def save(self, record: InboundRecord) -> None:
        """Persists the inbound record into the partition-backed storage."""
        ...

    @abstractmethod
    async def get_by_id(self, record_id: str, tenant_id: str) -> InboundRecord | None:
        """Retrieves an inbound record by primary key scoped to tenant."""
        ...

    @abstractmethod
    async def get_by_trace_id(
        self, trace_id: str, tenant_id: str
    ) -> Sequence[InboundRecord]:
        """Retrieves all inbound records associated with a trace ID."""
        ...
