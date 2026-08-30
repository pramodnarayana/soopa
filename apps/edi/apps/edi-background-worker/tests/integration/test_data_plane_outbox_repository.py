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

    # Monkeypatch get_engine to inject schema_translate_map at execution time
    original_get_engine = router.get_engine

    async def mock_get_engine(db_key: str, url: str | None = None):
        engine = await original_get_engine(db_key, url)
        return engine

    monkeypatch.setattr(router, "get_engine", mock_get_engine)

    # Global db has all the schema
    await router.get_engine("global", base_url)

    async for session in router.get_global_session():
        from sqlalchemy import delete
        from ucp_models.infrastructure import DatabaseShard

        await session.execute(delete(DatabaseShard))

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


@pytest.fixture(autouse=True)
async def clear_outbox(test_session: AsyncSession) -> None:
    from sqlalchemy import text

    await test_session.execute(text("TRUNCATE TABLE edi.outbox RESTART IDENTITY CASCADE;"))
    await test_session.commit()


@pytest.fixture
async def test_session(db_router: DatabaseRouter) -> "AsyncGenerator[AsyncSession, None]":
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = await db_router.get_engine("shard_1")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        yield session


@pytest.mark.integration
async def test_claim_next_events_and_mark_completed(
    db_router: DatabaseRouter, test_session: AsyncSession
) -> None:
    builder = DataPlaneOutboxBuilder(session=test_session)
    event1 = await builder.create(event_type="TEST_EVENT_1")
    event2 = await builder.create(event_type="TEST_EVENT_2")
    await test_session.commit()

    repo = PostgresEdiDataPlaneOutboxRepository(db_router=db_router)

    # Test claiming events
    worker_id = "test-worker-1"
    events = await repo.claim_next_events(worker_id=worker_id, limit=2)
    assert len(events) >= 2
    claimed_ids = {e.id for e in events}
    assert str(event1.id) in claimed_ids
    assert str(event2.id) in claimed_ids

    # Try to claim more events, should return none because they are locked
    more_events = await repo.claim_next_events(worker_id="test-worker-2", limit=2)
    assert len(more_events) == 0

    # Mark one completed
    await repo.mark_completed(event_id=str(event1.id), worker_id=worker_id)

    # Mark one failed
    await repo.mark_failed(event_id=str(event2.id), worker_id=worker_id, error_message="some error")

    # Let's verify status directly via the test session
    await test_session.refresh(event1)
    await test_session.refresh(event2)

    assert event1.status == OutboxStatus.PROCESSED.value
    assert event2.status == OutboxStatus.PENDING.value
    assert event2.attempts == 1
    assert event2.error_reason == "some error"

    # Sweep stuck events should do nothing right now since lease hasn't expired
    swept = await repo.sweep_stuck_events()
    assert swept == 0


@pytest.mark.integration
async def test_mark_failed_max_attempts(
    db_router: DatabaseRouter, test_session: AsyncSession
) -> None:
    builder = DataPlaneOutboxBuilder(session=test_session)
    # Set attempts to 2 so the next failure exceeds max_attempts (3)
    event = await builder.create(event_type="TEST_EVENT_FAILED", attempts=2)
    await test_session.commit()

    repo = PostgresEdiDataPlaneOutboxRepository(db_router=db_router)
    worker_id = "test-worker-failure"

    events = await repo.claim_next_events(worker_id=worker_id, limit=1)
    assert len(events) >= 1

    await repo.mark_failed(event_id=str(event.id), worker_id=worker_id, error_message="fatal error")

    await test_session.refresh(event)
    assert event.status == OutboxStatus.FAILED.value
