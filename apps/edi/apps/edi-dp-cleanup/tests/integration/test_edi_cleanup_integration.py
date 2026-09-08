import os
from datetime import UTC, datetime, timedelta

import pytest
from database.router import DatabaseRouter
from edi.adapters.outbound.database.models.data_plane import (
    AuditLog,
    DataPlaneOutbox,
    ProcessedEvent,
)
from edi.domain.enums import AuditLogStatus
from outbox.application.outbox_cleaner_use_case import (
    OutboxCleanerUseCase,
)
from outbox.domain.constants import OutboxStatus
from sqlalchemy import select

from edi_dp_cleanup.adapters.outbound.database.postgres_edi_audit_log_cleanup_repository import (
    SqlAlchemyEdiAuditLogCleanupRepository,
)
from edi_dp_cleanup.adapters.outbound.database.postgres_edi_data_plane_outbox_cleanup_repository import (
    SqlAlchemyEdiDataPlaneOutboxCleanupRepository,
)
from edi_dp_cleanup.adapters.outbound.database.postgres_edi_idempotency_cleanup_repository import (
    SqlAlchemyEdiIdempotencyCleanupRepository,
)
from edi_dp_cleanup.application.use_cases.edi_audit_log_cleanup_use_case import (
    EdiAuditLogCleanupUseCase,
)
from edi_dp_cleanup.application.use_cases.edi_idempotency_cleanup_use_case import (
    EdiIdempotencyCleanupUseCase,
)

pytestmark = pytest.mark.integration


@pytest.mark.integration
async def test_edi_data_plane_outbox_cleanup(db_router: DatabaseRouter) -> None:

    old_date = datetime.now(UTC) - timedelta(days=15)
    recent_date = datetime.now(UTC) - timedelta(days=1)

    async for test_session in db_router.get_shard_session("ucp_shard_1", "mock_dsn"):
        ob1_id = f"dp_edi_ob_{os.urandom(12).hex()}"
        ob2_id = f"dp_edi_ob_{os.urandom(12).hex()}"
        ob3_id = f"dp_edi_ob_{os.urandom(12).hex()}"

        # Add old processed (should be deleted)
        ob1 = DataPlaneOutbox(
            id=ob1_id,
            tenant_id="tenant-1",
            idempotency_key=f"iam_key_{os.urandom(12).hex()}",
            status=OutboxStatus.PROCESSED.value,
            event_type="TEST",
            payload={},
            created_at=old_date,
            updated_at=old_date,
        )
        # Add old pending (should NOT be deleted)
        ob2 = DataPlaneOutbox(
            id=ob2_id,
            tenant_id="tenant-1",
            idempotency_key=f"iam_key_{os.urandom(12).hex()}",
            status=OutboxStatus.PENDING.value,
            event_type="TEST",
            payload={},
            created_at=old_date,
            updated_at=old_date,
        )
        # Add recent processed (should NOT be deleted)
        ob3 = DataPlaneOutbox(
            id=ob3_id,
            tenant_id="tenant-1",
            idempotency_key=f"iam_key_{os.urandom(12).hex()}",
            status=OutboxStatus.PROCESSED.value,
            event_type="TEST",
            payload={},
            created_at=recent_date,
            updated_at=recent_date,
        )
        test_session.add_all([ob1, ob2, ob3])
        await test_session.commit()

    repo = SqlAlchemyEdiDataPlaneOutboxCleanupRepository(db_router)
    use_case = OutboxCleanerUseCase(repository=repo, retention_days=14)
    await use_case.execute()

    async for test_session in db_router.get_shard_session("ucp_shard_1", "mock_dsn"):
        result = await test_session.execute(select(DataPlaneOutbox.id))
        remaining = {r for (r,) in result.all()}

        assert ob1_id not in remaining
        assert ob2_id in remaining
        assert ob3_id in remaining


@pytest.mark.integration
async def test_edi_idempotency_cleanup(db_router: DatabaseRouter) -> None:

    old_date = datetime.now(UTC) - timedelta(days=15)
    recent_date = datetime.now(UTC) - timedelta(days=1)

    async for test_session in db_router.get_shard_session("ucp_shard_1", "mock_dsn"):
        key1 = f"iam_key_{os.urandom(12).hex()}"
        key2 = f"iam_key_{os.urandom(12).hex()}"

        # Add old
        ev1 = ProcessedEvent(
            idempotency_key=key1,
            tenant_id="tenant-1",
            processed_at=old_date,
        )
        # Add recent
        ev2 = ProcessedEvent(
            idempotency_key=key2,
            tenant_id="tenant-1",
            processed_at=recent_date,
        )
        test_session.add_all([ev1, ev2])
        await test_session.commit()

    repo = SqlAlchemyEdiIdempotencyCleanupRepository(db_router)
    use_case = EdiIdempotencyCleanupUseCase(repository=repo, retention_days=14)
    await use_case.execute()

    async for test_session in db_router.get_shard_session("ucp_shard_1", "mock_dsn"):
        result = await test_session.execute(select(ProcessedEvent.idempotency_key))
        remaining = {r for (r,) in result.all()}

        assert key1 not in remaining
        assert key2 in remaining


@pytest.mark.integration
async def test_edi_audit_log_cleanup(db_router: DatabaseRouter) -> None:

    old_date = datetime.now(UTC) - timedelta(days=15)
    recent_date = datetime.now(UTC) - timedelta(days=1)

    async for test_session in db_router.get_shard_session("ucp_shard_1", "mock_dsn"):
        audit_1_id = f"audit_{os.urandom(12).hex()}"
        audit_2_id = f"audit_{os.urandom(12).hex()}"

        # Add old
        al1 = AuditLog(
            id=audit_1_id,
            trace_id="trace1",
            step="step1",
            status=AuditLogStatus.SUCCESS,
            tenant_id="tenant-1",
            created_at=old_date,
            updated_at=old_date,
        )
        # Add recent
        al2 = AuditLog(
            id=audit_2_id,
            trace_id="trace2",
            step="step2",
            status=AuditLogStatus.SUCCESS,
            tenant_id="tenant-1",
            created_at=recent_date,
            updated_at=recent_date,
        )
        test_session.add_all([al1, al2])
        await test_session.commit()

    repo = SqlAlchemyEdiAuditLogCleanupRepository(db_router)
    use_case = EdiAuditLogCleanupUseCase(repository=repo, retention_days=14)
    await use_case.execute()

    async for test_session in db_router.get_shard_session("ucp_shard_1", "mock_dsn"):
        result = await test_session.execute(select(AuditLog.id))
        remaining = {r for (r,) in result.all()}

        assert audit_1_id not in remaining
        assert audit_2_id in remaining


@pytest.mark.integration
async def test_bounded_two_shard_cleanup_failure_propagates(
    db_router: DatabaseRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = SqlAlchemyEdiAuditLogCleanupRepository(db_router=db_router)

    # Force a failure on shard_1 by patching db_router.get_shard_session
    original_get_shard_session = db_router.get_shard_session

    async def mock_get_all_shards():
        return [("ucp_shard_1", "mock_dsn_1"), ("ucp_shard_2", "mock_dsn_2")]

    monkeypatch.setattr(db_router, "get_all_shards", mock_get_all_shards)

    async def mock_fail_session(shard_name: str, dsn: str | None = None):
        if shard_name == "ucp_shard_1":
            raise RuntimeError("Database connection lost for shard_1")
        # Yield from original generator
        async for session in original_get_shard_session(shard_name, dsn):
            yield session

    monkeypatch.setattr(db_router, "get_shard_session", mock_fail_session)

    try:
        with pytest.raises(ExceptionGroup) as exc_info:
            await repo.cleanup_audit_logs(retention_days=30)

        # Verify grouped failure propagation
        assert "shard_cleanup_had_failures" in str(exc_info.value)
        assert len(exc_info.value.exceptions) == 1
        assert "Database connection lost for shard_1" in str(exc_info.value.exceptions[0])
    finally:
        monkeypatch.undo()
