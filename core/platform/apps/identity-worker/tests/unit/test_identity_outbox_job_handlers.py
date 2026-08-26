from unittest.mock import AsyncMock

import pytest
from identity_worker.adapters.inbound.jobs.identity_outbox_cleanup_job import (
    IdentityOutboxCleanupJobHandler,
)
from identity_worker.adapters.inbound.jobs.identity_outbox_sweeper_job import (
    IdentityOutboxSweeperJobHandler,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler_type",
    [IdentityOutboxCleanupJobHandler, IdentityOutboxSweeperJobHandler],
)
async def test_outbox_job_handler_propagates_use_case_failure(handler_type) -> None:
    use_case = AsyncMock()
    use_case.execute.side_effect = RuntimeError("outbox failure")

    with pytest.raises(RuntimeError, match="outbox failure"):
        await handler_type(use_case).execute()
