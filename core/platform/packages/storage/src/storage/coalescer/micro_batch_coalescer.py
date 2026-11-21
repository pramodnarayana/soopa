"""Universal In-Memory Micro-Batch Coalescer (core/platform/packages/storage/coalescer)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from typing import Generic, TypeVar

import structlog
from seedwork.utils import generate_id

from storage.coalescer.ports import BatchFlusherPort
from storage.domain.dtos import CoalescerMetricsDTO

T = TypeVar("T")
logger = structlog.get_logger(__name__)


class MicroBatchCoalescer(Generic[T]):
    """Thread-safe, sliding-window buffer that coalesces high-frequency items into micro-batches.

    Eviction is triggered when either:
    1. Count threshold is reached (e.g., 25,000 items).
    2. Time threshold is exceeded (e.g., 60.0 seconds).
    """

    def __init__(
        self,
        tenant_id: str,
        stream_name: str,
        flusher: BatchFlusherPort[T],
        batch_size_threshold: int = 25_000,
        max_window_seconds: float = 60.0,
    ) -> None:
        self.tenant_id = tenant_id
        self.stream_name = stream_name
        self._flusher = flusher
        self._batch_size_threshold = batch_size_threshold
        self._max_window_seconds = max_window_seconds

        self._buffer: list[T] = []
        self._window_start_time: float = time.monotonic()
        self._lock = asyncio.Lock()
        self._total_flushes: int = 0
        self._total_records_flushed: int = 0

    @property
    def current_buffer_size(self) -> int:
        return len(self._buffer)

    @property
    def window_elapsed_seconds(self) -> float:
        return time.monotonic() - self._window_start_time

    async def push(self, record: T) -> bool:
        """Pushes a single record into the buffer and flushes if eviction conditions are met.

        Returns True if a flush was triggered, False otherwise.
        """
        async with self._lock:
            self._buffer.append(record)
            if self._should_flush_unlocked():
                await self._execute_flush_unlocked()
                return True
            return False

    async def push_many(self, records: Iterable[T]) -> bool:
        """Pushes multiple records into the buffer and flushes if eviction conditions are met."""
        async with self._lock:
            self._buffer.extend(records)
            if self._should_flush_unlocked():
                await self._execute_flush_unlocked()
                return True
            return False

    async def flush_if_needed(self) -> bool:
        """Evaluates time and size triggers and flushes if overdue."""
        async with self._lock:
            if self._should_flush_unlocked():
                await self._execute_flush_unlocked()
                return True
            return False

    async def flush_all(self) -> int:
        """Forced flush of all buffered items regardless of size/time (e.g., on shutdown).

        Returns number of flushed items.
        """
        async with self._lock:
            if not self._buffer:
                return 0
            count = len(self._buffer)
            await self._execute_flush_unlocked()
            return count

    def get_metrics(self) -> CoalescerMetricsDTO:
        """Returns snapshot metrics for monitoring and health reporting."""
        return CoalescerMetricsDTO(
            tenant_id=self.tenant_id,
            stream_name=self.stream_name,
            buffered_count=len(self._buffer),
            batch_size_threshold=self._batch_size_threshold,
            window_duration_seconds=self.window_elapsed_seconds,
            total_flushes=self._total_flushes,
            total_records_flushed=self._total_records_flushed,
        )

    def _should_flush_unlocked(self) -> bool:
        if not self._buffer:
            return False
        return (
            len(self._buffer) >= self._batch_size_threshold
            or self.window_elapsed_seconds >= self._max_window_seconds
        )

    async def _execute_flush_unlocked(self) -> None:
        if not self._buffer:
            return

        batch_id = generate_id("bat")
        items_to_flush = tuple(self._buffer)
        item_count = len(items_to_flush)
        self._buffer.clear()
        self._window_start_time = time.monotonic()

        logger.info(
            "coalescer_flushing_batch",
            tenant_id=self.tenant_id,
            stream_name=self.stream_name,
            batch_id=batch_id,
            item_count=item_count,
        )

        try:
            await self._flusher.flush_batch(
                tenant_id=self.tenant_id,
                stream_name=self.stream_name,
                batch_id=batch_id,
                records=items_to_flush,
            )
            self._total_flushes += 1
            self._total_records_flushed += item_count
            logger.info(
                "coalescer_batch_flushed_success",
                tenant_id=self.tenant_id,
                stream_name=self.stream_name,
                batch_id=batch_id,
                item_count=item_count,
            )
        except Exception:
            logger.exception(
                "coalescer_batch_flush_failed",
                tenant_id=self.tenant_id,
                stream_name=self.stream_name,
                batch_id=batch_id,
                item_count=item_count,
            )
            raise
