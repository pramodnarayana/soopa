"""Outbound port for chunked retention pruning of trace_events and processed_events."""

from __future__ import annotations

from typing import Protocol


class TraceRetentionRepositoryPort(Protocol):
    """Port for pruning expired trace ledger entries and consumer idempotency records."""

    async def cleanup_trace_events(
        self, retention_days: int, concurrency_limit: int = 5
    ) -> int: ...

    async def cleanup_processed_events(
        self, retention_days: int, concurrency_limit: int = 5
    ) -> int: ...


__all__ = ["TraceRetentionRepositoryPort"]
