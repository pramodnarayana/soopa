"""Testing utilities and in-memory fakes for the Soopa platform trace package."""

from __future__ import annotations

from collections.abc import Sequence

from strace.domain import TraceEvent, TraceLineageItemDTO
from strace.ports import TraceRepositoryPort


class InMemoryTraceRepository(TraceRepositoryPort):
    """In-memory implementation of TraceRepositoryPort for hexagonal application tests."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self._lineage_by_tenant: dict[str, list[TraceLineageItemDTO]] = {}

    def seed_lineage_item(self, tenant_id: str, item: TraceLineageItemDTO) -> None:
        self._lineage_by_tenant.setdefault(tenant_id, []).append(item)

    async def list_trace_events(
        self,
        tenant_id: str,
        trace_id: str,
    ) -> list[TraceEvent]:
        matching = [
            evt for evt in self.events if evt.tenant_id == tenant_id and evt.trace_id == trace_id
        ]
        return sorted(matching, key=lambda evt: evt.created_at)

    async def save_trace_event(
        self,
        event: TraceEvent,
    ) -> None:
        self.events.append(event)

    async def save_all_trace_events(
        self,
        events: Sequence[TraceEvent],
    ) -> None:
        self.events.extend(events)

    async def resolve_root_trace_id(
        self,
        tenant_id: str,
        trace_id: str,
        stage_models_deepest_first: Sequence[type[object]] | None = None,
    ) -> str:
        _ = stage_models_deepest_first
        for item in self._lineage_by_tenant.get(tenant_id, []):
            if item.trace_id == trace_id and item.original_trace_id:
                return item.original_trace_id
        return trace_id

    async def get_trace_lineage(
        self,
        tenant_id: str,
        trace_id: str,
    ) -> list[TraceLineageItemDTO]:
        root_trace_id = await self.resolve_root_trace_id(tenant_id, trace_id)
        items = [
            item
            for item in self._lineage_by_tenant.get(tenant_id, [])
            if item.trace_id == root_trace_id or item.original_trace_id == root_trace_id
        ]
        return sorted(
            items,
            key=lambda item: (item.replay_count, str(item.created_at or "")),
        )

    async def find_traces_by_correlation_id(
        self,
        tenant_id: str,
        correlation_id: str,
        *,
        limit: int = 50,
    ) -> list[TraceLineageItemDTO]:
        items = [
            item
            for item in self._lineage_by_tenant.get(tenant_id, [])
            if item.correlation_id == correlation_id
        ]
        sorted_items = sorted(
            items,
            key=lambda item: str(item.created_at or ""),
            reverse=True,
        )
        return sorted_items[:limit]


__all__ = [
    "InMemoryTraceRepository",
]
