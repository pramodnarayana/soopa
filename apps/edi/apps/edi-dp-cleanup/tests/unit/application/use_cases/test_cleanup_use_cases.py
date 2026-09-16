import pytest

from edi_dp_cleanup.application.use_cases.edi_idempotency_cleanup_use_case import (
    EdiIdempotencyCleanupUseCase,
)
from edi_dp_cleanup.ports.outbound.edi_idempotency_cleanup_repository_port import (
    EdiIdempotencyCleanupRepositoryPort,
)


class FakeIdempotencyRepo(EdiIdempotencyCleanupRepositoryPort):
    async def cleanup_idempotency_results(self, retention_days: int) -> None:
        pass


def test_idempotency_cleanup_use_case_validation():
    with pytest.raises(ValueError, match="retention_days cannot be negative"):
        EdiIdempotencyCleanupUseCase(repository=FakeIdempotencyRepo(), retention_days=-1)
