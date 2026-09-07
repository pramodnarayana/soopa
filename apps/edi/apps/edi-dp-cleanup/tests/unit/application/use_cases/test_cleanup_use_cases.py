from unittest.mock import MagicMock

import pytest

from edi_dp_cleanup.application.use_cases.edi_audit_log_cleanup_use_case import (
    EdiAuditLogCleanupUseCase,
)
from edi_dp_cleanup.application.use_cases.edi_idempotency_cleanup_use_case import (
    EdiIdempotencyCleanupUseCase,
)


def test_audit_log_cleanup_use_case_validation():
    mock_repo = MagicMock()
    with pytest.raises(ValueError, match="retention_days cannot be negative"):
        EdiAuditLogCleanupUseCase(repository=mock_repo, retention_days=-1)


def test_idempotency_cleanup_use_case_validation():
    mock_repo = MagicMock()
    with pytest.raises(ValueError, match="retention_days cannot be negative"):
        EdiIdempotencyCleanupUseCase(repository=mock_repo, retention_days=-1)
