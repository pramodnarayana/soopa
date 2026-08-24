import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

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
from worker.adapters.outbound.database.postgres_edi_audit_log_cleanup_repository import (
    SqlAlchemyEdiAuditLogCleanupRepository,
)
from worker.adapters.sqs_poller import _process_message_task
from worker.application.use_cases.edi_audit_log_cleanup_use_case import (
    EdiAuditLogCleanupUseCase,
)
from worker.data.scheduled_jobs_handler import process_scheduled_job
from worker.domain.job_registry import JobHandlerRegistry
from worker.domain.scheduler.models import Job


class _SingleConcurrencyAuditLogCleanupRepository:
    def __init__(self, repository: SqlAlchemyEdiAuditLogCleanupRepository) -> None:
        self.repository = repository

    async def cleanup_audit_logs(self, retention_days: int, concurrency_limit: int = 5) -> None:
        await self.repository.cleanup_audit_logs(retention_days, concurrency_limit=1)


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


@pytest.mark.asyncio
async def test_grouped_two_shard_failures_leave_scheduled_job_for_retry() -> None:
    global_session = AsyncMock()
    shard_result = MagicMock()
    shard_result.scalars.return_value.all.return_value = [
        SimpleNamespace(name="shard_1", dsn="postgresql+asyncpg://shard-1"),
        SimpleNamespace(name="shard_2", dsn="postgresql+asyncpg://shard-2"),
    ]
    global_session.execute.return_value = shard_result

    async def get_global_session():
        yield global_session

    db_router = MagicMock()
    db_router.get_global_session = get_global_session
    db_router.get_engine = AsyncMock(
        side_effect=[RuntimeError("shard 1 unavailable"), RuntimeError("shard 2 unavailable")]
    )
    cleanup_repository = _SingleConcurrencyAuditLogCleanupRepository(
        SqlAlchemyEdiAuditLogCleanupRepository(db_router)
    )
    handler = EdiAuditLogCleanupJobHandler(EdiAuditLogCleanupUseCase(cleanup_repository))
    registry = JobHandlerRegistry()
    registry.register("EDI_AUDIT_LOG_CLEANUP", handler)

    grouped_failure: ExceptionGroup | None = None

    async def process_and_capture(message: dict[str, Any]) -> None:
        nonlocal grouped_failure
        try:
            await process_scheduled_job(message, registry=registry)
        except ExceptionGroup as exc:
            grouped_failure = exc
            raise

    receipt_handle = await _process_message_task(
        "edi-orchestrator-jobs",
        {
            "ReceiptHandle": "receipt-1",
            "Body": (
                '{"job_id": "00000000-0000-0000-0000-000000000001", '
                '"job_name": "EDI_AUDIT_LOG_CLEANUP", "payload": {}}'
            ),
        },
        process_and_capture,
    )

    assert receipt_handle is None
    assert grouped_failure is not None
    assert len(grouped_failure.exceptions) == 2
    assert {str(exc) for exc in grouped_failure.exceptions} == {
        "shard 1 unavailable",
        "shard 2 unavailable",
    }
    assert db_router.get_engine.await_count == 2
