"""Port contract for storing and querying Layer 2 ReplicaRecord entities."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from seedwork.domain.types import JsonDict, JsonPrimitive

from ip.engine.domain.enums import MergeOutcome
from ip.engine.domain.models.replica_record import ReplicaRecord


@dataclass(frozen=True)
class ReplicaMergeCandidate:
    """Input parameters for a candidate record to merge into the replica store."""

    tenant_id: str
    connection_id: str
    stream: str
    record_key: str
    primary_key_values: tuple[JsonPrimitive, ...]
    cursor_value: str | None
    cursor_kind: str | None
    data: JsonDict
    data_hash: str
    generation_id: int
    source_inbound_record_id: str
    trace_id: str
    correlation_id: str | None = None
    is_deleted: bool = False


@dataclass(frozen=True)
class MergeResult:
    """Outcome of merging a candidate record into the replica ledger."""

    record_id: str
    stream: str
    record_key: str
    outcome: MergeOutcome
    version: int
    data_hash: str


class ReplicaRecordRepositoryPort(Protocol):
    """Outbound repository port for Layer 2 universal replica snapshots."""

    @abstractmethod
    async def save(self, record: ReplicaRecord) -> None:
        """Persists or updates the replica snapshot and flushes domain events."""
        ...

    @abstractmethod
    async def get_by_id(
        self,
        tenant_id: str,
        record_id: str,
    ) -> ReplicaRecord | None:
        """Retrieves an existing replica snapshot by primary record ID."""
        ...

    @abstractmethod
    async def get_by_key(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
        record_key: str,
    ) -> ReplicaRecord | None:
        """Retrieves an existing replica snapshot by stream and record key."""
        ...

    @abstractmethod
    async def merge_batch(
        self,
        candidates: Sequence[ReplicaMergeCandidate],
    ) -> list[MergeResult]:
        """Bulk merges a batch of extracted records, returning per-row merge outcomes."""
        ...

    @abstractmethod
    async def tombstone_unseen_generations(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
        current_generation: int,
        limit: int = 500,
        trace_id: str = "",
    ) -> int:
        """Tombstones rows where last_seen_generation < current_generation for full-refresh syncs."""
        ...

    @abstractmethod
    async def list_by_stream_chunk(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        stream: str,
        after_id: str | None = None,
        limit: int = 100,
    ) -> list[ReplicaRecord]:
        """Retrieves a deterministic keyset-paginated chunk of replica records for a stream."""
        ...

    async def get_by_trace_id(
        self,
        trace_id: str,
        tenant_id: str,
    ) -> Sequence[ReplicaRecord]:
        """Retrieves all replica records last updated under a given trace ID."""
        return ()
