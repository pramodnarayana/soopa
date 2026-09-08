import pytest

from edi_dp_cleanup.application.use_cases.edi_audit_log_cleanup_use_case import (
    EdiAuditLogCleanupUseCase,
)
from edi_dp_cleanup.application.use_cases.edi_idempotency_cleanup_use_case import (
    EdiIdempotencyCleanupUseCase,
)
from edi_dp_cleanup.ports.outbound.edi_audit_log_cleanup_repository_port import (
    EdiAuditLogCleanupRepositoryPort,
)
from edi_dp_cleanup.ports.outbound.edi_idempotency_cleanup_repository_port import (
    EdiIdempotencyCleanupRepositoryPort,
)


class FakeAuditRepo(EdiAuditLogCleanupRepositoryPort):
    async def cleanup_audit_logs(self, retention_days: int) -> None:
        pass


class FakeIdempotencyRepo(EdiIdempotencyCleanupRepositoryPort):
    async def cleanup_idempotency_results(self, retention_days: int) -> None:
        pass


def test_audit_log_cleanup_use_case_validation():
    with pytest.raises(ValueError, match="retention_days cannot be negative"):
        EdiAuditLogCleanupUseCase(repository=FakeAuditRepo(), retention_days=-1)


def test_idempotency_cleanup_use_case_validation():
    with pytest.raises(ValueError, match="retention_days cannot be negative"):
        EdiIdempotencyCleanupUseCase(repository=FakeIdempotencyRepo(), retention_days=-1)
