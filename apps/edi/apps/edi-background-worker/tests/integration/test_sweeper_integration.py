import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from outbox.application.outbox_sweeper_use_case import (
    OutboxSweeperUseCase,
)
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.infrastructure import DatabaseShard

from edi_background_worker.adapters.outbound.database.postgres_edi_data_plane_outbox_cleanup_repository import (
    SqlAlchemyEdiDataPlaneOutboxCleanupRepository,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def db_router() -> "AsyncGenerator[DatabaseRouter, None]":
    # Use standard local environment DB URL
    global_url = os.getenv(
        "GLOBAL_DB_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
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

    from edi.adapters.outbound.database.models.data_plane import TenantBase

    async with engine.begin() as conn:
        await conn.run_sync(TenantBase.metadata.create_all)

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
                    "id": f"dp_edi_ob_{uuid.uuid4().hex[:24]}",
                    "tenant_id": "ten_default_123",
                    "idempotency_key": f"idemp_{uuid.uuid4()}",
                    "event_type": "TRANSFORM_EVENT",
                    "payload": {},
                    "status": "PENDING",
                    "attempts": 0,
                    "created_at": created_at,
                    "updated_at": datetime.now(UTC),
                },
                {
                    "id": f"dp_edi_ob_{uuid.uuid4().hex[:24]}",
                    "tenant_id": "ten_default_123",
                    "idempotency_key": f"idemp_{uuid.uuid4()}",
                    "event_type": "DELIVER_EVENT",
                    "payload": {},
                    "status": "PENDING",
                    "attempts": 0,
                    "created_at": created_at,
                    "updated_at": datetime.now(UTC),
                },
            ]
        )
    )
    await test_session.commit()

    # 2. Mock external SQS boundary (allowed by Enterprise Rules)
    mock_publisher = MagicMock()
    mock_publisher.publish_batch = AsyncMock(side_effect=lambda events: [e.id for e in events])

    repo = SqlAlchemyEdiDataPlaneOutboxCleanupRepository(db_router=db_router)

    use_case = OutboxSweeperUseCase(repository=repo, publisher=mock_publisher)

    # 3. Execute Sweeper against real local DB
    await use_case.execute()

    # 4. Verify
    mock_publisher.publish_batch.assert_called()


@pytest.mark.integration
async def test_bounded_two_shard_cleanup_failure_propagates(
    db_router: DatabaseRouter, test_session: AsyncSession
) -> None:
    from ucp_models.infrastructure import DatabaseShard

    from edi_background_worker.adapters.outbound.database.postgres_edi_audit_log_cleanup_repository import (
        SqlAlchemyEdiAuditLogCleanupRepository,
    )

    created_shard_2 = False

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
                    "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global",
                ),
            )
            session.add(shard)
            await session.commit()
            created_shard_2 = True

    repo = SqlAlchemyEdiAuditLogCleanupRepository(db_router=db_router)

    # Force a failure on shard_1 by patching db_router.get_engine to raise an exception
    original_get_engine = db_router.get_engine

    async def mock_get_engine(shard_name: str, dsn: str | None = None):
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
        try:
            if created_shard_2:
                async for session in db_router.get_global_session():
                    await session.execute(
                        delete(DatabaseShard).where(DatabaseShard.id == "test_shard_id_2")
                    )
                    await session.commit()
        finally:
            db_router.get_engine = original_get_engine
