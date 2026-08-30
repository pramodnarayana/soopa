from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from edi.adapters.outbound.database.connection import DatabaseRouter
from outbox.application.outbox_cleaner_use_case import (
    OutboxCleanerUseCase,
)
from outbox.domain.constants import OutboxStatus
from sqlalchemy.ext.asyncio import AsyncSession

from edi_background_worker.adapters.outbound.database.postgres_edi_audit_log_cleanup_repository import (
    SqlAlchemyEdiAuditLogCleanupRepository,
)
from edi_background_worker.adapters.outbound.database.postgres_edi_data_plane_outbox_cleanup_repository import (
    SqlAlchemyEdiDataPlaneOutboxCleanupRepository,
)
from edi_background_worker.adapters.outbound.database.postgres_edi_idempotency_cleanup_repository import (
    SqlAlchemyEdiIdempotencyCleanupRepository,
)
from edi_background_worker.application.use_cases.edi_audit_log_cleanup_use_case import (
    EdiAuditLogCleanupUseCase,
)
from edi_background_worker.application.use_cases.edi_idempotency_cleanup_use_case import (
    EdiIdempotencyCleanupUseCase,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def db_router() -> "AsyncGenerator[DatabaseRouter, None]":
    import os

    from database.provider import get_async_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    global_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
    ).replace("postgresql://", "postgresql+asyncpg://")
    shard_url = os.getenv(
        "SHARD_1_URL", "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"
    ).replace("postgresql://", "postgresql+asyncpg://")

    global_engine = get_async_engine(global_url)
    shard_engine = get_async_engine(shard_url)

    global_conn = await global_engine.connect()
    global_trans = await global_conn.begin()

    shard_conn = await shard_engine.connect()
    shard_trans = await shard_conn.begin()

    import asyncio

    db_lock = asyncio.Lock()

    class TestDatabaseRouter(DatabaseRouter):
        async def get_global_session(self):
            async with db_lock:
                factory = async_sessionmaker(
                    bind=global_conn,
                    expire_on_commit=False,
                    class_=AsyncSession,
                    join_transaction_mode="create_savepoint",
                )
                async with factory() as session:
                    yield session

        async def get_shard_session(self, shard_key: str, shard_url: str):
            async with db_lock:
                factory = async_sessionmaker(
                    bind=shard_conn,
                    expire_on_commit=False,
                    class_=AsyncSession,
                    join_transaction_mode="create_savepoint",
                )
                async with factory() as session:
                    yield session

        async def get_all_shards(self):
            return [("shard_1", shard_url)]

    yield TestDatabaseRouter(global_db_url=global_url)

    await global_trans.rollback()
    await global_conn.close()
    await global_engine.dispose()

    await shard_trans.rollback()
    await shard_conn.close()
    await shard_engine.dispose()


@pytest.mark.integration
async def test_edi_data_plane_outbox_cleanup(db_router: DatabaseRouter) -> None:
    import os

    from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox

    old_date = datetime.now(UTC) - timedelta(days=15)
    recent_date = datetime.now(UTC) - timedelta(days=1)

    async for test_session in db_router.get_shard_session("shard_1", "mock_dsn"):
        ob1_id = f"dp_edi_ob_{os.urandom(12).hex()}"
        ob2_id = f"dp_edi_ob_{os.urandom(12).hex()}"
        ob3_id = f"dp_edi_ob_{os.urandom(12).hex()}"

        # Add old processed (should be deleted)
        ob1 = DataPlaneOutbox(
            id=ob1_id,
            tenant_id="tenant-1",
            idempotency_key=f"key_{os.urandom(12).hex()}",
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
            idempotency_key=f"key_{os.urandom(12).hex()}",
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
            idempotency_key=f"key_{os.urandom(12).hex()}",
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

    async for test_session in db_router.get_shard_session("shard_1", "mock_dsn"):
        from sqlalchemy import select

        result = await test_session.execute(select(DataPlaneOutbox.id))
        remaining = {r for (r,) in result.all()}

        assert ob1_id not in remaining
        assert ob2_id in remaining
        assert ob3_id in remaining


@pytest.mark.integration
async def test_edi_idempotency_cleanup(db_router: DatabaseRouter) -> None:
    from edi.adapters.outbound.database.models.data_plane import ProcessedEvent

    old_date = datetime.now(UTC) - timedelta(days=15)
    recent_date = datetime.now(UTC) - timedelta(days=1)

    async for test_session in db_router.get_shard_session("shard_1", "mock_dsn"):
        import os

        key1 = f"key_{os.urandom(12).hex()}"
        key2 = f"key_{os.urandom(12).hex()}"

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

    async for test_session in db_router.get_shard_session("shard_1", "mock_dsn"):
        from sqlalchemy import select

        result = await test_session.execute(select(ProcessedEvent.idempotency_key))
        remaining = {r for (r,) in result.all()}

        assert key1 not in remaining
        assert key2 in remaining


@pytest.mark.integration
async def test_edi_audit_log_cleanup(db_router: DatabaseRouter) -> None:
    from edi.adapters.outbound.database.models.data_plane import AuditLog

    old_date = datetime.now(UTC) - timedelta(days=15)
    recent_date = datetime.now(UTC) - timedelta(days=1)

    async for test_session in db_router.get_shard_session("shard_1", "mock_dsn"):
        import os

        audit_1_id = f"audit_{os.urandom(12).hex()}"
        audit_2_id = f"audit_{os.urandom(12).hex()}"

        # Add old
        al1 = AuditLog(
            id=audit_1_id,
            trace_id="trace1",
            step="step1",
            status="SUCCESS",
            tenant_id="tenant-1",
            created_at=old_date,
            updated_at=old_date,
        )
        # Add recent
        al2 = AuditLog(
            id=audit_2_id,
            trace_id="trace2",
            step="step2",
            status="SUCCESS",
            tenant_id="tenant-1",
            created_at=recent_date,
            updated_at=recent_date,
        )
        test_session.add_all([al1, al2])
        await test_session.commit()

    repo = SqlAlchemyEdiAuditLogCleanupRepository(db_router)
    use_case = EdiAuditLogCleanupUseCase(repository=repo, retention_days=14)
    await use_case.execute()

    async for test_session in db_router.get_shard_session("shard_1", "mock_dsn"):
        from sqlalchemy import select

        result = await test_session.execute(select(AuditLog.id))
        remaining = {r for (r,) in result.all()}

        assert audit_1_id not in remaining
        assert audit_2_id in remaining
