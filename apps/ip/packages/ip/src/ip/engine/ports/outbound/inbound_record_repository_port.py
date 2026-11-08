"""Port contract for storing and querying Layer 1 InboundRecord audit records."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.replication.inbound_record import InboundRecord


class InboundRecordRepositoryPort(Protocol):
    """Outbound repository port for Layer 1 raw inbound records."""

    @abstractmethod
    async def save(self, record: InboundRecord) -> None:
        """Persists the inbound record into the partition-backed storage."""
        ...

    async def save_batch(self, records: Sequence[InboundRecord]) -> None:
        """Persists an ordered batch of inbound records atomically inside the active transaction."""
        for record in records:
            await self.save(record)

    @abstractmethod
    async def get_by_id(self, record_id: str, tenant_id: str) -> InboundRecord | None:
        """Retrieves an inbound record by primary key scoped to tenant."""
        ...

    @abstractmethod
    async def list_by_range(
        self,
        tenant_id: str,
        *,
        batch_id: str = "",
        range_start: str = "",
        range_end: str = "",
        record_ids: Sequence[str] = (),
    ) -> Sequence[InboundRecord]:
        """Retrieves an ordered slice of inbound records for a Range Claim-Check (`[range_start .. range_end]`)."""
        ...

    @abstractmethod
    async def get_by_trace_id(
        self,
        trace_id: str,
        tenant_id: str,
        *,
        hydrate_payloads: bool = False,
    ) -> Sequence[InboundRecord]:
        """Retrieves all inbound records associated with a trace ID."""
        ...

    @abstractmethod
    async def get_by_external_event_id(
        self,
        tenant_id: str,
        connection_id: str,
        external_event_id: str,
    ) -> InboundRecord | None:
        """Retrieves an inbound record by external push event ID for deduplication."""
        ...

    async def list_records(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
        stream_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
        hydrate_payloads: bool = False,
    ) -> Sequence[InboundRecord]:
        """Lists inbound wire records filtered by connection and/or stream name."""
        return ()
