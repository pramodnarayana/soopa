import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.infrastructure import DatabaseShard

from worker.application.use_cases.edi_data_plane_outbox_sweeper_use_case import (
    EdiDataPlaneOutboxSweeperUseCase,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def db_router() -> "AsyncGenerator[DatabaseRouter, None]":
    # Use standard local environment DB URL
    global_url = os.getenv(
        "GLOBAL_DB_URL", "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_global"
    )
    router = DatabaseRouter(global_db_url=global_url)

    # Ensure shard exists
    async for session in router.get_global_session():
        from sqlalchemy import select

        res = await session.execute(select(DatabaseShard).where(DatabaseShard.name == "shard_1"))
        shard = res.scalars().first()
        if not shard:
            shard = DatabaseShard(
                id="test_shard_id",
                name="shard_1",
                dsn=os.getenv(
                    "SHARD_1_URL",
                    "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1",
                ),
            )
            session.add(shard)
            await session.commit()

    yield router
    await router.close_all()


@pytest.fixture
async def test_session(db_router: DatabaseRouter) -> "AsyncGenerator[AsyncSession, None]":
    shard_url = os.getenv(
        "SHARD_1_URL", "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"
    )
    engine = await db_router.get_engine("shard_1", shard_url)
    async with AsyncSession(engine) as session:
        # Cleanup before
        await session.execute(delete(DataPlaneOutbox))
        await session.commit()

        yield session

        # Cleanup after
        await session.execute(delete(DataPlaneOutbox))
        await session.commit()


@pytest.mark.integration
async def test_sweeper_fetches_and_processes_events(
    db_router: DatabaseRouter, test_session: AsyncSession
) -> None:
    # 1. Setup real DB records
    created_at = datetime.now(UTC) - timedelta(minutes=6)
    await test_session.execute(
        insert(DataPlaneOutbox).values(
            [
                {
                    "id": 1,
                    "event_type": "EDI_RECEIVED",
                    "payload": {},
                    "created_at": created_at,
                },
                {
                    "id": 2,
                    "event_type": "EDI_PROCESSED",
                    "payload": {},
                    "created_at": created_at,
                },
            ]
        )
    )
    await test_session.commit()

    # 2. Mock external SQS boundary (allowed by Enterprise Rules)
    mock_publisher = MagicMock()
    mock_publisher.publish_batch = AsyncMock(return_value=[])

    use_case = EdiDataPlaneOutboxSweeperUseCase(
        db_router=db_router, message_publisher=mock_publisher
    )

    # Mock processor to simulate successfully processing the batch
    use_case.processor.process_batch = AsyncMock(return_value=2)

    # 3. Execute Sweeper against real local DB
    processed = await use_case.execute()

    # 4. Verify
    assert processed >= 2
    use_case.processor.process_batch.assert_called_once()


@pytest.mark.integration
async def test_bounded_two_shard_cleanup_failure_propagates(db_router: DatabaseRouter) -> None:
    from ucp_models.infrastructure import DatabaseShard

    from worker.adapters.outbound.database.postgres_edi_audit_log_cleanup_repository import (
        SqlAlchemyEdiAuditLogCleanupRepository,
    )

    # Inject a second shard for the test
    async for session in db_router.get_global_session():
        from sqlalchemy import select

        res = await session.execute(select(DatabaseShard).where(DatabaseShard.name == "shard_2"))
        shard = res.scalars().first()
        if not shard:
            shard = DatabaseShard(
                id="test_shard_id_2",
                name="shard_2",
                dsn=os.getenv(
                    "SHARD_2_URL",
                    "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_2",
                ),
            )
            session.add(shard)
            await session.commit()

    repo = SqlAlchemyEdiAuditLogCleanupRepository(db_router=db_router)

    # Force a failure on shard_1 by patching db_router.get_engine to raise an exception
    original_get_engine = db_router.get_engine

    async def mock_get_engine(shard_name: str, dsn: str):
        if shard_name == "shard_1":
            raise RuntimeError("Database connection lost for shard_1")
        return await original_get_engine(shard_name, dsn)

    db_router.get_engine = mock_get_engine

    try:
        with pytest.raises(ExceptionGroup) as exc_info:
            await repo.cleanup_audit_logs(retention_days=30)

        # Verify grouped failure propagation
        assert "shard_cleanup_had_failures" in str(exc_info.value)
        assert len(exc_info.value.exceptions) == 1
        assert "Database connection lost for shard_1" in str(exc_info.value.exceptions[0])
    finally:
        db_router.get_engine = original_get_engine
