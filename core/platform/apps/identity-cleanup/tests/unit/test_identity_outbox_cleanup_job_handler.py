import pytest

from identity_cleanup.adapters.inbound.jobs.identity_outbox_cleanup_job import (
    IdentityOutboxCleanupJobHandler,
)


class FailingUseCase:
    async def execute(self) -> None:
        raise RuntimeError("outbox failure")


@pytest.mark.asyncio
async def test_outbox_cleanup_job_handler_propagates_use_case_failure() -> None:
    use_case = FailingUseCase()

    with pytest.raises(RuntimeError, match="outbox failure"):
        await IdentityOutboxCleanupJobHandler(use_case).execute()
