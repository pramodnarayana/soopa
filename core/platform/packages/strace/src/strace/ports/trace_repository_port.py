"""Outbound repository port for distributed business traces across bounded contexts."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import Protocol

from strace.domain.enums import TraceStatus
from strace.domain.models import TraceEvent, TraceLineageItemDTO


class TraceRepositoryPort(Protocol):
    """Generic outbound port for querying trace events, replay lineage trees, and business correlation keys."""

    @abstractmethod
    async def list_trace_events(
        self,
        tenant_id: str,
        trace_id: str,
    ) -> list[TraceEvent]:
        """Returns all immutable TraceEvent ledger entries for trace_id in chronological order."""
        ...

    @abstractmethod
    async def save_trace_event(
        self,
        event: TraceEvent,
    ) -> None:
        """Persists a single TraceEvent ledger entry."""
        ...

    @abstractmethod
    async def save_all_trace_events(
        self,
        events: Sequence[TraceEvent],
    ) -> None:
        """Persists a batch of TraceEvent ledger entries."""
        ...

    @abstractmethod
    async def resolve_root_trace_id(
        self,
        tenant_id: str,
        trace_id: str,
    ) -> str:
        """Resolves the root original_trace_id for a trace across configured stage tables."""
        ...

    @abstractmethod
    async def get_trace_lineage(
        self,
        tenant_id: str,
        trace_id: str,
    ) -> list[TraceLineageItemDTO]:
        """Returns all execution attempts sharing the same original_trace_id root in chronological order."""
        ...

    @abstractmethod
    async def find_traces_by_correlation_id(
        self,
        tenant_id: str,
        correlation_id: str,
        *,
        limit: int = 50,
    ) -> list[TraceLineageItemDTO]:
        """Finds trace summaries matching a business correlation key (e.g. meter_id, order_id, control_no)."""
        ...

    @abstractmethod
    async def list_recent_traces(
        self,
        tenant_id: str,
        *,
        status: TraceStatus | None = None,
        min_replay_count: int | None = None,
        limit: int = 50,
    ) -> list[TraceLineageItemDTO]:
        """Returns the most recent trace summaries for a tenant ordered newest-first."""
        ...


__all__ = ["TraceRepositoryPort"]
