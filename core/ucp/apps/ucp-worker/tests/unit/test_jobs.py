import uuid
from unittest.mock import AsyncMock

import pytest

from ucp_worker.adapters.inbound.jobs.ucp_audit_log_cleanup_job import UcpAuditLogCleanupJobHandler
from ucp_worker.adapters.inbound.jobs.ucp_idempotency_cleanup_job import (
    UcpIdempotencyCleanupJobHandler,
)
from ucp_worker.adapters.inbound.jobs.ucp_outbox_cleanup_job import UcpOutboxCleanupJobHandler
from ucp_worker.adapters.inbound.jobs.ucp_outbox_sweeper_job import UcpOutboxSweeperJobHandler
from ucp_worker.core.scheduler.models import Job


@pytest.fixture
def dummy_job() -> Job:
    return Job(id=uuid.uuid4(), name="test_job", payload={})


@pytest.mark.asyncio
async def test_audit_log_cleanup_job(dummy_job: Job) -> None:
    use_case = AsyncMock()
    handler = UcpAuditLogCleanupJobHandler(use_case=use_case)
    await handler.execute(dummy_job)
    use_case.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_idempotency_cleanup_job(dummy_job: Job) -> None:
    use_case = AsyncMock()
    handler = UcpIdempotencyCleanupJobHandler(use_case=use_case)
    await handler.execute(dummy_job)
    use_case.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_outbox_cleanup_job(dummy_job: Job) -> None:
    use_case = AsyncMock()
    handler = UcpOutboxCleanupJobHandler(use_case=use_case)
    await handler.execute(dummy_job)
    use_case.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_outbox_sweeper_job(dummy_job: Job) -> None:
    use_case = AsyncMock()
    handler = UcpOutboxSweeperJobHandler(use_case=use_case)
    await handler.execute(dummy_job)
    use_case.execute.assert_awaited_once()
