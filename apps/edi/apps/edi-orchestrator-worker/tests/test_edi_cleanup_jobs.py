import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from worker.domain.scheduler.models import Job

from worker.adapters.inbound.jobs.edi_audit_log_cleanup_job import (
    EdiAuditLogCleanupJobHandler,
)
from worker.adapters.inbound.jobs.edi_control_plane_outbox_cleanup_job import (
    EdiControlPlaneOutboxCleanupJobHandler,
)
from worker.adapters.inbound.jobs.edi_data_plane_outbox_cleanup_job import (
    EdiDataPlaneOutboxCleanupJobHandler,
)
from worker.adapters.inbound.jobs.edi_idempotency_cleanup_job import (
    EdiIdempotencyCleanupJobHandler,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler_class,job_name",
    [
        (EdiControlPlaneOutboxCleanupJobHandler, "edi_control_plane_outbox_cleanup"),
        (EdiDataPlaneOutboxCleanupJobHandler, "edi_data_plane_outbox_cleanup"),
        (EdiIdempotencyCleanupJobHandler, "edi_idempotency_cleanup"),
        (EdiAuditLogCleanupJobHandler, "edi_audit_log_cleanup"),
    ],
)
async def test_edi_cleanup_execute(handler_class: Any, job_name: str) -> None:
    mock_use_case = MagicMock()
    mock_use_case.execute = AsyncMock()

    handler = handler_class(use_case=mock_use_case)

    job = Job(id=uuid.uuid4(), name=job_name, payload={}, interval_seconds=120)
    next_run = await handler.execute(job)

    assert mock_use_case.execute.await_count == 1
    assert next_run is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler_class,job_name",
    [
        (EdiControlPlaneOutboxCleanupJobHandler, "edi_control_plane_outbox_cleanup"),
        (EdiDataPlaneOutboxCleanupJobHandler, "edi_data_plane_outbox_cleanup"),
        (EdiIdempotencyCleanupJobHandler, "edi_idempotency_cleanup"),
        (EdiAuditLogCleanupJobHandler, "edi_audit_log_cleanup"),
    ],
)
async def test_edi_cleanup_execute_exception_propagates(handler_class: Any, job_name: str) -> None:
    mock_use_case = MagicMock()
    mock_use_case.execute = AsyncMock(side_effect=Exception("DB Down"))

    handler = handler_class(use_case=mock_use_case)

    job = Job(id=uuid.uuid4(), name=job_name, payload={}, interval_seconds=120)

    with pytest.raises(Exception, match="DB Down"):
        await handler.execute(job)
