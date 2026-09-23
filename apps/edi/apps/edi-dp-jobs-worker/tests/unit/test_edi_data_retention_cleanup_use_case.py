import pytest

from edi_dp_jobs_worker.application.use_cases.edi_data_retention_cleanup_use_case import (
    EdiDataRetentionCleanupUseCase,
)
from edi_dp_jobs_worker.ports.outbound.edi_data_retention_cleanup_repository_port import (
    EdiDataRetentionCleanupRepositoryPort,
)


class FakeEdiDataRetentionCleanupRepository(EdiDataRetentionCleanupRepositoryPort):
    def __init__(self) -> None:
        self.cleanup_processed_events_called_with_days: int | None = None
        self.cleanup_trace_events_called_with_days: int | None = None
        self.should_fail_trace_events = False

    async def cleanup_processed_events(
        self, retention_days: int, concurrency_limit: int = 5
    ) -> None:
        self.cleanup_processed_events_called_with_days = retention_days

    async def cleanup_trace_events(self, retention_days: int, concurrency_limit: int = 5) -> None:
        if self.should_fail_trace_events:
            raise RuntimeError("Failed to cleanup traces")
        self.cleanup_trace_events_called_with_days = retention_days


def test_init_raises_on_negative_retention_days():
    repo = FakeEdiDataRetentionCleanupRepository()
    with pytest.raises(ValueError, match="retention_days cannot be negative"):
        EdiDataRetentionCleanupUseCase(repository=repo, retention_days=-1)


@pytest.mark.asyncio
async def test_execute_success():
    repo = FakeEdiDataRetentionCleanupRepository()
    use_case = EdiDataRetentionCleanupUseCase(repository=repo, retention_days=10)

    await use_case.execute()

    assert repo.cleanup_processed_events_called_with_days == 10
    assert repo.cleanup_trace_events_called_with_days == 10


@pytest.mark.asyncio
async def test_execute_raises_exception_group_on_failures():
    repo = FakeEdiDataRetentionCleanupRepository()
    repo.should_fail_trace_events = True

    use_case = EdiDataRetentionCleanupUseCase(repository=repo, retention_days=10)

    with pytest.raises(ExceptionGroup) as exc_info:
        await use_case.execute()

    assert exc_info.value.message == "data_retention_cleanup_had_failures"
    assert len(exc_info.value.exceptions) == 1
    assert isinstance(exc_info.value.exceptions[0], RuntimeError)

    assert repo.cleanup_processed_events_called_with_days == 10
