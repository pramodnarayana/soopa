from unittest.mock import AsyncMock

import pytest

from identity_outbox_worker.adapters.inbound.jobs.identity_outbox_sweeper_job import (
    IdentityOutboxSweeperJobHandler,
)


@pytest.mark.asyncio
async def test_outbox_sweeper_job_handler_propagates_use_case_failure() -> None:
    use_case = AsyncMock()
    use_case.execute.side_effect = RuntimeError("outbox failure")

    with pytest.raises(RuntimeError, match="outbox failure"):
        await IdentityOutboxSweeperJobHandler(use_case).execute()
