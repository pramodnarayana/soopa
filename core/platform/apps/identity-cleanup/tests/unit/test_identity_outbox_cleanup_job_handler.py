from unittest.mock import AsyncMock

import pytest

from identity_cleanup.adapters.inbound.jobs.identity_outbox_cleanup_job import (
    IdentityOutboxCleanupJobHandler,
)


@pytest.mark.asyncio
async def test_outbox_cleanup_job_handler_propagates_use_case_failure() -> None:
    use_case = AsyncMock()
    use_case.execute.side_effect = RuntimeError("outbox failure")

    with pytest.raises(RuntimeError, match="outbox failure"):
        await IdentityOutboxCleanupJobHandler(use_case).execute()
