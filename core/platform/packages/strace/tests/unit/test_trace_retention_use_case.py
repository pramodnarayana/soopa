"""Unit tests for CleanTraceRetentionUseCase in strace (Zero Mocks)."""

from __future__ import annotations

import pytest

from strace.application.clean_trace_retention_use_case import (
    CleanTraceRetentionCommand,
    CleanTraceRetentionUseCase,
)
from strace.ports.retention_repository_port import TraceRetentionRepositoryPort


class FakeTraceRetentionRepository(TraceRetentionRepositoryPort):
    def __init__(self) -> None:
        self.trace_calls: list[tuple[int, int]] = []
        self.processed_calls: list[tuple[int, int]] = []

    async def cleanup_trace_events(self, retention_days: int, concurrency_limit: int = 5) -> int:
        self.trace_calls.append((retention_days, concurrency_limit))
        return 120

    async def cleanup_processed_events(
        self, retention_days: int, concurrency_limit: int = 5
    ) -> int:
        self.processed_calls.append((retention_days, concurrency_limit))
        return 45


@pytest.mark.asyncio
async def test_clean_trace_retention_use_case_executes_both_cleanups() -> None:
    repo = FakeTraceRetentionRepository()
    use_case = CleanTraceRetentionUseCase(repository=repo)

    res = await use_case.execute(
        CleanTraceRetentionCommand(
            trace_retention_days=30,
            processed_event_retention_days=7,
            concurrency_limit=3,
        )
    )
    assert res.trace_events_deleted == 120
    assert res.processed_events_deleted == 45
    assert repo.trace_calls == [(30, 3)]
    assert repo.processed_calls == [(7, 3)]
