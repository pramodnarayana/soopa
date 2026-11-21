"""Ports for micro-batch coalescing and buffer flushing."""

from __future__ import annotations

from typing import Protocol, TypeVar

T_contra = TypeVar("T_contra", contravariant=True)


class BatchFlusherPort(Protocol[T_contra]):
    """Generic outbound port invoked when a micro-batch triggers eviction."""

    async def flush_batch(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        records: tuple[T_contra, ...],
    ) -> None:
        """Flushes a consolidated micro-batch to downstream targets (S3, Parquet, OLAP)."""
        ...
