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
async def db_router() -> "AsyncGenerator[DatabaseRouter, None]":
    import os

    from database.provider import get_async_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    global_url = (
        os.getenv(
            "DATABASE_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
        )
        .replace("postgres://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )
    shard_url = (
        os.getenv("SHARD_1_URL", "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1")
        .replace("postgres://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )

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
async def test_sweeper_fetches_and_processes_events(db_router: DatabaseRouter):
    # 1. Setup Data - stuck events that need sweeping
    async for test_session in db_router.get_shard_session("shard_1", "mock_dsn"):
        builder = DataPlaneOutboxBuilder(session=test_session)
        # We will create events with default properties that makes them look "stuck".
        # e.g., in PROCESSING state but with lease expired (which happens when sweep_stuck_events runs).
        # Actually sweep_stuck_events resets them to PENDING so they can be claimed again.

        # We'll just create pending events to simulate they were swept and can now be published.
        # Note: the sweep stuck logic resets them, then the sweeper daemon claims them.
        event1 = await builder.create(event_type="TRANSFORM_EVENT", status="PROCESSING")
        event2 = await builder.create(event_type="DELIVER_EVENT", status="PROCESSING")

        # Manually force them to be "stuck" by setting lease_expires_at to the past
        import datetime

        event1.lease_expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )
        event2.lease_expires_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            minutes=10
        )

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

    # Force a failure on shard_1 by patching db_router.get_shard_session
    original_get_shard_session = db_router.get_shard_session

    async def mock_fail_session(shard_name: str, dsn: str | None = None):
        if shard_name == "shard_1":
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
