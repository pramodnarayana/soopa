import uuid
from typing import Any

import pytest

from edi_background_worker.adapters.inbound.jobs.edi_audit_log_cleanup_job import (
    EdiAuditLogCleanupJobHandler,
)
from edi_background_worker.adapters.inbound.jobs.edi_data_plane_outbox_cleanup_job import (
    EdiDataPlaneOutboxCleanupJobHandler,
)
from edi_background_worker.adapters.inbound.jobs.edi_idempotency_cleanup_job import (
    EdiIdempotencyCleanupJobHandler,
)
from edi_background_worker.adapters.outbound.database.postgres_edi_audit_log_cleanup_repository import (
    SqlAlchemyEdiAuditLogCleanupRepository,
)
from edi_background_worker.application.use_cases.edi_audit_log_cleanup_use_case import (
    EdiAuditLogCleanupUseCase,
)
from edi_background_worker.domain.job_registry import JobHandlerRegistry
from edi_background_worker.domain.scheduler.models import Job
from edi_background_worker.scheduled_jobs_handler import process_scheduled_job


class _SingleConcurrencyAuditLogCleanupRepository:
    def __init__(self, repository: SqlAlchemyEdiAuditLogCleanupRepository) -> None:
        self.repository = repository

    async def cleanup_audit_logs(self, retention_days: int, concurrency_limit: int = 5) -> None:
        await self.repository.cleanup_audit_logs(retention_days, concurrency_limit=1)


class FakeUseCase:
    def __init__(self) -> None:
        self.execute_count = 0
        self.should_raise = False

    async def execute(self) -> None:
        if self.should_raise:
            raise RuntimeError("DB Down")
        self.execute_count += 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler_class,job_name",
    [
        (EdiDataPlaneOutboxCleanupJobHandler, "edi_data_plane_outbox_cleanup"),
        (EdiIdempotencyCleanupJobHandler, "edi_idempotency_cleanup"),
        (EdiAuditLogCleanupJobHandler, "edi_audit_log_cleanup"),
    ],
)
async def test_edi_cleanup_execute(handler_class: Any, job_name: str) -> None:
    fake_use_case = FakeUseCase()

    handler = handler_class(use_case=fake_use_case)

    job = Job(id=uuid.uuid4(), name=job_name, payload={}, interval_seconds=120)
    next_run = await handler.execute(job)

    assert fake_use_case.execute_count == 1
    assert next_run is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler_class,job_name",
    [
        (EdiDataPlaneOutboxCleanupJobHandler, "edi_data_plane_outbox_cleanup"),
        (EdiIdempotencyCleanupJobHandler, "edi_idempotency_cleanup"),
        (EdiAuditLogCleanupJobHandler, "edi_audit_log_cleanup"),
    ],
)
async def test_edi_cleanup_execute_exception_propagates(handler_class: Any, job_name: str) -> None:
    fake_use_case = FakeUseCase()
    fake_use_case.should_raise = True

    handler = handler_class(use_case=fake_use_case)

    job = Job(id=uuid.uuid4(), name=job_name, payload={}, interval_seconds=120)

    with pytest.raises(Exception, match="DB Down"):
        await handler.execute(job)


@pytest.mark.asyncio
async def test_grouped_two_shard_failures_leave_scheduled_job_for_retry() -> None:
    class FakeDbRouter:
        def __init__(self) -> None:
            self.get_engine_count = 0

        async def get_all_shards(self) -> list[tuple[str, str]]:
            return [
                ("shard_1", "postgresql+asyncpg://shard-1"),
                ("shard_2", "postgresql+asyncpg://shard-2"),
            ]

        async def get_engine(self, tenant_id: str, dsn: str = "") -> Any:
            self.get_engine_count += 1
            if tenant_id == "shard_1":
                raise RuntimeError("shard 1 unavailable")
            if tenant_id == "shard_2":
                raise RuntimeError("shard 2 unavailable")
            return None

    db_router = FakeDbRouter()
    cleanup_repository = _SingleConcurrencyAuditLogCleanupRepository(
        SqlAlchemyEdiAuditLogCleanupRepository(db_router)  # type: ignore
    )
    handler = EdiAuditLogCleanupJobHandler(EdiAuditLogCleanupUseCase(cleanup_repository))  # type: ignore
    registry = JobHandlerRegistry()
    registry.register("EDI_AUDIT_LOG_CLEANUP", handler)

    grouped_failure = None
    try:
        await process_scheduled_job(
            {
                "job_id": "00000000-0000-0000-0000-000000000001",
                "job_name": "EDI_AUDIT_LOG_CLEANUP",
                "payload": {},
            },
            registry=registry,
        )
    except ExceptionGroup as exc:
        grouped_failure = exc

    assert grouped_failure is not None
    assert len(grouped_failure.exceptions) == 2
    assert {str(exc) for exc in grouped_failure.exceptions} == {
        "shard 1 unavailable",
        "shard 2 unavailable",
    }
    assert db_router.get_engine_count == 2
