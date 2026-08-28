from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.testing.factories.outbox import DataPlaneOutboxBuilder
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from sqlalchemy.ext.asyncio import AsyncSession

from edi_background_worker.adapters.outbound.database.postgres_edi_audit_log_cleanup_repository import (
    SqlAlchemyEdiAuditLogCleanupRepository,
)
from edi_background_worker.adapters.outbound.database.postgres_edi_data_plane_outbox_repository import (
    PostgresEdiDataPlaneOutboxRepository,
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

    # 2. Monkeypatch get_engine to inject schema_translate_map at execution time
    original_get_engine = router.get_engine

    async def mock_get_engine(db_key: str, url: str | None = None):
        engine = await original_get_engine(db_key, url)
        return engine

    monkeypatch.setattr(router, "get_engine", mock_get_engine)

    # Global db has all the schema
    await router.get_engine("global", base_url)

    async for session in router.get_global_session():
        from ucp_models.infrastructure import DatabaseShard

        shard1 = DatabaseShard(id="test_shard_id", name="shard_1", dsn=shard_1_url)
        shard2 = DatabaseShard(id="test_shard_id_2", name="shard_2", dsn=shard_1_url)
        await session.merge(shard1)
        await session.merge(shard2)
        await session.commit()

    # Pre-warm shard connections
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


@pytest.mark.integration
async def test_sweeper_fetches_and_processes_events(
    db_router: DatabaseRouter, test_session: AsyncSession
) -> None:
    # 1. Setup real DB records using ORM Factory
    builder = DataPlaneOutboxBuilder(session=test_session)
    await builder.create(event_type="TRANSFORM_EVENT")
    await builder.create(event_type="DELIVER_EVENT")
    await test_session.commit()

    # 2. Mock external SQS boundary
    mock_publisher = MagicMock()
    mock_publisher.publish_batch = AsyncMock(side_effect=lambda events: [e.id for e in events])

    repo = PostgresEdiDataPlaneOutboxRepository(db_router=db_router)

    use_case = OutboxSweeperUseCase(
        repository=repo, publisher=mock_publisher
    )  # 3. Execute Sweeper against real local DB
    await use_case.execute()

    # 4. Verify
    assert mock_publisher.publish_batch.call_count == 1
    call_args = mock_publisher.publish_batch.call_args[0][0]
    assert len(call_args) == 2


@pytest.mark.integration
async def test_bounded_two_shard_cleanup_failure_propagates(
    db_router: DatabaseRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = SqlAlchemyEdiAuditLogCleanupRepository(db_router=db_router)

    # Force a failure on shard_1 by patching db_router.get_engine
    original_get_engine = db_router.get_engine

    async def mock_fail_engine(shard_name: str, dsn: str | None = None):
        if shard_name == "shard_1":
            raise RuntimeError("Database connection lost for shard_1")
        return await original_get_engine(shard_name, dsn)

    monkeypatch.setattr(db_router, "get_engine", mock_fail_engine)

    try:
        with pytest.raises(ExceptionGroup) as exc_info:
            await repo.cleanup_audit_logs(retention_days=30)

        # Verify grouped failure propagation
        assert "shard_cleanup_had_failures" in str(exc_info.value)
        assert len(exc_info.value.exceptions) == 1
        assert "Database connection lost for shard_1" in str(exc_info.value.exceptions[0])
    finally:
        monkeypatch.undo()
