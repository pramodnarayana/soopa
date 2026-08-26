import uuid
from datetime import UTC, datetime

import pytest
from identity_worker.adapters.outbound.database.postgres_identity_outbox_repository import (
    PostgresIdentityOutboxRepository,
)
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def repo(db_session_factory):
    return PostgresIdentityOutboxRepository(db_session_factory)


async def test_claim_next_events_and_mark_completed(repo, db_session_factory):
    event_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    async with db_session_factory() as session:
        await session.execute(
            text("""
                INSERT INTO identity.outbox
                (id, event_type, payload, status, created_at, idempotency_key)
                VALUES (:id, 'UserCreated', '{}', 'PENDING', :now, 'key-1')
            """),
            {
                "id": event_id,
                "now": datetime.now(UTC),
            },
        )
        await session.commit()

    events = await repo.claim_next_events(worker_id=worker_id, limit=5, lock_lease_ms=30000)

    assert len(events) == 1
    assert events[0].id == event_id

    async with db_session_factory() as session:
        result = await session.execute(
            text("SELECT owner_token, lease_expires_at FROM identity.outbox WHERE id = :id"),
            {"id": event_id},
        )
        row = result.fetchone()
        assert row.owner_token == worker_id
        assert row.lease_expires_at is not None

    await repo.mark_completed(event_id, worker_id)

    async with db_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT status, owner_token, lease_expires_at FROM identity.outbox WHERE id = :id"
            ),
            {"id": event_id},
        )
        row = result.fetchone()
        assert row.status == "COMPLETED"
        assert row.owner_token is None
        assert row.lease_expires_at is None


async def test_mark_failed(repo, db_session_factory):
    event_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())

    async with db_session_factory() as session:
        await session.execute(
            text("""
                INSERT INTO identity.outbox
                (id, event_type, payload, status, created_at, owner_token, idempotency_key)
                VALUES (:id, 'Ping', '{}', 'PROCESSING', :now, :locked_by, 'key-2')
            """),
            {"id": event_id, "now": datetime.now(UTC), "locked_by": worker_id},
        )
        await session.commit()

    await repo.mark_failed(event_id, worker_id, "Simulated Error")

    async with db_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT status, error_reason, owner_token, lease_expires_at FROM identity.outbox WHERE id = :id"
            ),
            {"id": event_id},
        )
        row = result.fetchone()
        assert row.status == "FAILED"
        assert row.error_reason == "Simulated Error"
        assert row.owner_token is None
        assert row.lease_expires_at is None
