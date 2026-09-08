from typing import cast

import pytest
from database.router import DatabaseRouter

from edi_dp_cleanup.adapters.outbound.database.postgres_edi_audit_log_cleanup_repository import (
    SqlAlchemyEdiAuditLogCleanupRepository,
)
from edi_dp_cleanup.adapters.outbound.database.postgres_edi_data_plane_outbox_cleanup_repository import (
    SqlAlchemyEdiDataPlaneOutboxCleanupRepository,
)
from edi_dp_cleanup.adapters.outbound.database.postgres_edi_idempotency_cleanup_repository import (
    SqlAlchemyEdiIdempotencyCleanupRepository,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "repo_class",
    [
        SqlAlchemyEdiAuditLogCleanupRepository,
        SqlAlchemyEdiDataPlaneOutboxCleanupRepository,
        SqlAlchemyEdiIdempotencyCleanupRepository,
    ],
)
async def test_repository_concurrency_limit_validation(repo_class):
    mock_db_router = cast(DatabaseRouter, object())
    repo = repo_class(db_router=mock_db_router)

    with pytest.raises(ValueError, match="concurrency_limit must be strictly positive"):
        # We need to find the correct method to call depending on the repo
        if hasattr(repo, "cleanup_audit_logs"):
            await repo.cleanup_audit_logs(retention_days=7, concurrency_limit=0)
        elif hasattr(repo, "cleanup_outbox"):
            await repo.cleanup_outbox(retention_days=7, concurrency_limit=-1)
        elif hasattr(repo, "cleanup_idempotency_results"):
            await repo.cleanup_idempotency_results(retention_days=7, concurrency_limit=0)
