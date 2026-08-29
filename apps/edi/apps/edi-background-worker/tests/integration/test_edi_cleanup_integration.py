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
async def db_router(monkeypatch: pytest.MonkeyPatch) -> "AsyncGenerator[DatabaseRouter, None]":
    import os

    base_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
    )
    if base_url.startswith("postgresql://"):
        base_url = base_url.replace("postgresql://", "postgresql+asyncpg://")

    shard_1_url = os.getenv(
        "SHARD_1_URL", "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"
    )
    if shard_1_url.startswith("postgresql://"):
        shard_1_url = shard_1_url.replace("postgresql://", "postgresql+asyncpg://")

    router = DatabaseRouter(global_db_url=base_url)

    original_get_engine = router.get_engine

    async def mock_get_engine(db_key: str, url: str | None = None):
        return await original_get_engine(db_key, url)

    monkeypatch.setattr(router, "get_engine", mock_get_engine)

    await router.get_engine("global", base_url)

    async for session in router.get_global_session():
        from ucp_models.infrastructure import DatabaseShard

        shard1 = DatabaseShard(id="test_shard_id", name="shard_1", dsn=shard_1_url)
        shard2 = DatabaseShard(id="test_shard_id_2", name="shard_2", dsn=shard_1_url)
        await session.merge(shard1)
        await session.merge(shard2)
        await session.commit()

    await router.get_engine("shard_1", shard_1_url)
    await router.get_engine("shard_2", shard_1_url)

    yield router
    await router.close_all()


@pytest.fixture
async def test_session(db_router: DatabaseRouter) -> "AsyncGenerator[AsyncSession, None]":
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = await db_router.get_engine("shard_1")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        yield session


@pytest.fixture(autouse=True)
async def clear_tables(test_session: AsyncSession) -> None:
    from sqlalchemy import text

    await test_session.execute(text("TRUNCATE TABLE edi.outbox RESTART IDENTITY CASCADE;"))
    await test_session.execute(
        text("TRUNCATE TABLE edi.processed_events RESTART IDENTITY CASCADE;")
    )
    await test_session.execute(text("TRUNCATE TABLE edi.audit_log RESTART IDENTITY CASCADE;"))
    await test_session.commit()


@pytest.mark.integration
async def test_edi_data_plane_outbox_cleanup(
    db_router: DatabaseRouter, test_session: AsyncSession
) -> None:
    from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox

    old_date = datetime.now(UTC) - timedelta(days=15)
    recent_date = datetime.now(UTC) - timedelta(days=1)

    # Add old processed
    ob1 = DataPlaneOutbox(
        id="dp_edi_ob_1",
        tenant_id="tenant-1",
        idempotency_key="key1",
        status=OutboxStatus.PROCESSED.value,
        event_type="TEST",
        payload={},
        created_at=old_date,
        updated_at=old_date,
    )
    # Add old pending (should NOT be deleted)
    ob2 = DataPlaneOutbox(
        id="dp_edi_ob_2",
        tenant_id="tenant-1",
        idempotency_key="key2",
        status=OutboxStatus.PENDING.value,
        event_type="TEST",
        payload={},
        created_at=old_date,
        updated_at=old_date,
    )
    # Add recent processed (should NOT be deleted)
    ob3 = DataPlaneOutbox(
        id="dp_edi_ob_3",
        tenant_id="tenant-1",
        idempotency_key="key3",
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

    from sqlalchemy import select

    result = await test_session.execute(select(DataPlaneOutbox.id))
    remaining = {r for (r,) in result.all()}

    assert "dp_edi_ob_1" not in remaining
    assert "dp_edi_ob_2" in remaining
    assert "dp_edi_ob_3" in remaining


@pytest.mark.integration
async def test_edi_idempotency_cleanup(
    db_router: DatabaseRouter, test_session: AsyncSession
) -> None:
    from edi.adapters.outbound.database.models.data_plane import ProcessedEvent

    old_date = datetime.now(UTC) - timedelta(days=15)
    recent_date = datetime.now(UTC) - timedelta(days=1)

    # Add old
    ev1 = ProcessedEvent(
        idempotency_key="key1",
        tenant_id="tenant-1",
        processed_at=old_date,
    )
    # Add recent
    ev2 = ProcessedEvent(
        idempotency_key="key2",
        tenant_id="tenant-1",
        processed_at=recent_date,
    )
    test_session.add_all([ev1, ev2])
    await test_session.commit()

    repo = SqlAlchemyEdiIdempotencyCleanupRepository(db_router)
    use_case = EdiIdempotencyCleanupUseCase(repository=repo, retention_days=14)
    await use_case.execute()

    from sqlalchemy import select

    result = await test_session.execute(select(ProcessedEvent.idempotency_key))
    remaining = {r for (r,) in result.all()}

    assert "key1" not in remaining
    assert "key2" in remaining


@pytest.mark.integration
async def test_edi_audit_log_cleanup(db_router: DatabaseRouter, test_session: AsyncSession) -> None:
    from edi.adapters.outbound.database.models.data_plane import AuditLog

    old_date = datetime.now(UTC) - timedelta(days=15)
    recent_date = datetime.now(UTC) - timedelta(days=1)

    # Add old
    al1 = AuditLog(
        id="audit_1",
        trace_id="trace1",
        step="step1",
        status="SUCCESS",
        tenant_id="tenant-1",
        created_at=old_date,
        updated_at=old_date,
    )
    # Add recent
    al2 = AuditLog(
        id="audit_2",
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

    from sqlalchemy import select

    result = await test_session.execute(select(AuditLog.id))
    remaining = {r for (r,) in result.all()}

    assert "audit_1" not in remaining
    assert "audit_2" in remaining
