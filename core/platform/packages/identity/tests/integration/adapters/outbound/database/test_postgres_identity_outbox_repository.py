import datetime

import pytest
from database.models.identity import IdentityOutbox as OrmIdentityOutbox
from outbox.domain.constants import OutboxStatus
from seedwork import generate_id
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from identity.adapters.outbound.database.postgres_identity_outbox_repository import (
    PostgresIdentityOutboxRepository,
)
from identity.domain.constants import DomainIdPrefix as IamPrefix

pytestmark = pytest.mark.integration


@pytest.fixture
async def outbox_session_factory(db_engine):
    """A real (non-wrapped) session factory for outbox tests that commits to the DB."""
    yield async_sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture
async def outbox_repo(outbox_session_factory):
    yield PostgresIdentityOutboxRepository(outbox_session_factory)


@pytest.fixture
async def create_dummy_outbox_event(outbox_session_factory):
    """Inserts a real, committed outbox event so the outbox_repo can see it."""
    created_event_ids: list[str] = []

    async def _create(
        status: str = OutboxStatus.PENDING.value,
        attempts: int = 0,
        lease_expires_at: datetime.datetime | None = None,
        updated_at: datetime.datetime | None = None,
    ) -> str:
        event_id = generate_id(IamPrefix.OUTBOX)
        now = updated_at or datetime.datetime.now(datetime.UTC).replace(tzinfo=None)

        async with outbox_session_factory() as session:
            stmt = pg_insert(OrmIdentityOutbox).values(
                id=event_id,
                idempotency_key=f"idemp_{event_id}",
                tenant_id=generate_id(IamPrefix.TENANT),
                event_type="TestEvent",
                payload={"test": "data"},
                status=status,
                attempts=attempts,
                lease_expires_at=lease_expires_at,
                created_at=now,
                updated_at=now,
            )
            await session.execute(stmt)
            await session.commit()

        created_event_ids.append(event_id)
        return event_id

    yield _create

    if created_event_ids:
        async with outbox_session_factory() as session:
            await session.execute(
                delete(OrmIdentityOutbox).where(OrmIdentityOutbox.id.in_(created_event_ids))
            )
            await session.commit()


@pytest.mark.asyncio
async def test_claim_next_events(outbox_repo, create_dummy_outbox_event) -> None:
    event_id_1 = await create_dummy_outbox_event()
    event_id_2 = await create_dummy_outbox_event()

    # Claim events
    events = await outbox_repo.claim_next_events("worker_1", 10, 5000)

    assert len(events) == 2
    claimed_ids = {e.id for e in events}
    assert event_id_1 in claimed_ids
    assert event_id_2 in claimed_ids


@pytest.mark.asyncio
async def test_sweep_stuck_events(outbox_repo, create_dummy_outbox_event) -> None:
    # Create an event stuck in processing (updated 10 seconds ago)
    stuck_time = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(
        seconds=10
    )
    stuck_event_id = await create_dummy_outbox_event(
        status=OutboxStatus.PROCESSING.value,
        updated_at=stuck_time,
    )

    # Sweep with a 5000ms (5s) lease
    swept_count = await outbox_repo.sweep_stuck_events(5000)

    assert swept_count == 1

    # Should now be claimable again
    events = await outbox_repo.claim_next_events("worker_2", 10, 5000)
    assert len(events) == 1
    assert events[0].id == stuck_event_id


@pytest.mark.asyncio
async def test_mark_completed_and_failed(
    outbox_repo, create_dummy_outbox_event, db_session_factory
) -> None:
    event_id = await create_dummy_outbox_event()
    worker_id = "worker_1"

    # Claim it
    events = await outbox_repo.claim_next_events(worker_id, 1, 5000)
    assert len(events) == 1

    # Mark failed
    await outbox_repo.mark_failed(event_id, worker_id, "Test error")

    # Verify it failed and went back to pending
    async with db_session_factory() as session:
        from sqlalchemy import select

        stmt = select(OrmIdentityOutbox).where(OrmIdentityOutbox.id == event_id)
        outbox = (await session.execute(stmt)).scalar_one()
        assert outbox.status == OutboxStatus.PENDING.value
        assert outbox.attempts == 1
        assert outbox.error_reason == "Test error"

    # Claim again and mark completed
    events = await outbox_repo.claim_next_events(worker_id, 1, 5000)
    assert len(events) == 1

    await outbox_repo.mark_completed(event_id, worker_id)

    # Verify it completed
    async with db_session_factory() as session:
        outbox = (await session.execute(stmt)).scalar_one()
        assert outbox.status == OutboxStatus.PROCESSED.value
