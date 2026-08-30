from collections.abc import AsyncGenerator

import pytest
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.testing.factories.outbox import DataPlaneOutboxBuilder
from outbox.domain.constants import OutboxStatus
from sqlalchemy.ext.asyncio import AsyncSession

from edi_background_worker.adapters.outbound.database.postgres_edi_data_plane_outbox_repository import (
    PostgresEdiDataPlaneOutboxRepository,
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
async def test_claim_next_events_and_mark_completed(db_router: DatabaseRouter) -> None:
    async for test_session in db_router.get_shard_session("shard_1", "mock_dsn"):
        builder = DataPlaneOutboxBuilder(session=test_session)
        event1 = await builder.create(event_type="TEST_EVENT_1")
        event2 = await builder.create(event_type="TEST_EVENT_2")
        await test_session.commit()
        event1_id = str(event1.id)
        event2_id = str(event2.id)

    repo = PostgresEdiDataPlaneOutboxRepository(db_router=db_router)

    # Test claiming events
    worker_id = "test-worker-1"
    events = await repo.claim_next_events(worker_id=worker_id, limit=2)
    assert len(events) >= 2
    claimed_ids = {e.id for e in events}
    assert event1_id in claimed_ids
    assert event2_id in claimed_ids

    # Try to claim more events, should return none because they are locked
    more_events = await repo.claim_next_events(worker_id="test-worker-2", limit=2)
    assert len(more_events) == 0

    # Mark one completed
    await repo.mark_completed(event_id=event1_id, worker_id=worker_id)

    # Mark one failed
    await repo.mark_failed(event_id=event2_id, worker_id=worker_id, error_message="some error")

    # Let's verify status directly via the test session
    async for test_session in db_router.get_shard_session("shard_1", "mock_dsn"):
        from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
        from sqlalchemy import select

        res1 = await test_session.execute(
            select(DataPlaneOutbox).where(DataPlaneOutbox.id == event1_id)
        )
        res2 = await test_session.execute(
            select(DataPlaneOutbox).where(DataPlaneOutbox.id == event2_id)
        )
        event1 = res1.scalars().first()
        event2 = res2.scalars().first()

        assert event1.status == OutboxStatus.PROCESSED.value
        assert event2.status == OutboxStatus.PENDING.value
        assert event2.attempts == 1
        assert event2.error_reason == "some error"

    # Sweep stuck events should do nothing right now since lease hasn't expired
    swept = await repo.sweep_stuck_events()
    assert swept == 0


@pytest.mark.integration
async def test_mark_failed_max_attempts(db_router: DatabaseRouter) -> None:
    async for test_session in db_router.get_shard_session("shard_1", "mock_dsn"):
        builder = DataPlaneOutboxBuilder(session=test_session)
        # Set attempts to 2 so the next failure exceeds max_attempts (3)
        event = await builder.create(event_type="TEST_EVENT_FAILED", attempts=2)
        await test_session.commit()
        event_id = str(event.id)

    repo = PostgresEdiDataPlaneOutboxRepository(db_router=db_router)
    worker_id = "test-worker-failure"

    events = await repo.claim_next_events(worker_id=worker_id, limit=1)
    assert len(events) >= 1

    await repo.mark_failed(event_id=event_id, worker_id=worker_id, error_message="fatal error")

    async for test_session in db_router.get_shard_session("shard_1", "mock_dsn"):
        from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
        from sqlalchemy import select

        res = await test_session.execute(
            select(DataPlaneOutbox).where(DataPlaneOutbox.id == event_id)
        )
        event = res.scalars().first()
        assert event.status == OutboxStatus.FAILED.value
