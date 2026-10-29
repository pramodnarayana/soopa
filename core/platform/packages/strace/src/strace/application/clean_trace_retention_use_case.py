"""Application use case for chunked retention cleanup of trace_events and processed_events."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from strace.ports.retention_repository_port import TraceRetentionRepositoryPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class CleanTraceRetentionCommand:
    """Command parameters for pruning expired trace events and processed event keys."""

    trace_retention_days: int = 90
    processed_event_retention_days: int = 3
    concurrency_limit: int = 5


@dataclass(frozen=True, kw_only=True)
class CleanTraceRetentionResultDTO:
    """Summary counts of deleted trace events and processed event keys."""

    trace_events_deleted: int
    processed_events_deleted: int


class CleanTraceRetentionUseCase:
    """Prunes expired trace_events and processed_events across tenant shards in chunked batches."""

    def __init__(self, repository: TraceRetentionRepositoryPort) -> None:
        self._repository = repository

    async def execute(
        self, command: CleanTraceRetentionCommand | None = None
    ) -> CleanTraceRetentionResultDTO:
        cmd = command or CleanTraceRetentionCommand()
        if cmd.trace_retention_days < 0 or cmd.processed_event_retention_days < 0:
            raise ValueError("retention_days cannot be negative")
        if cmd.concurrency_limit <= 0:
            raise ValueError("concurrency_limit must be strictly positive")

        logger.info(
            "trace_retention_cleanup_started",
            trace_retention_days=cmd.trace_retention_days,
            processed_event_retention_days=cmd.processed_event_retention_days,
            concurrency_limit=cmd.concurrency_limit,
        )
        processed_deleted = await self._repository.cleanup_processed_events(
            retention_days=cmd.processed_event_retention_days,
            concurrency_limit=cmd.concurrency_limit,
        )
        trace_deleted = await self._repository.cleanup_trace_events(
            retention_days=cmd.trace_retention_days,
            concurrency_limit=cmd.concurrency_limit,
        )
        logger.info(
            "trace_retention_cleanup_completed",
            trace_events_deleted=trace_deleted,
            processed_events_deleted=processed_deleted,
        )
        return CleanTraceRetentionResultDTO(
            trace_events_deleted=trace_deleted,
            processed_events_deleted=processed_deleted,
        )


__all__ = [
    "CleanTraceRetentionCommand",
    "CleanTraceRetentionResultDTO",
    "CleanTraceRetentionUseCase",
]
