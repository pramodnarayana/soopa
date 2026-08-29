import uuid

import pytest
from database.models.identity import Tenant

from notification.adapters.outbound.database.postgres_outbox_repository import (
    SqlAlchemyNotificationOutboxRepository,
)
from notification.domain.models import NotificationOutboxEvent


@pytest.mark.asyncio
async def test_outbox_save_and_fetch(db_session_factory):
    tenant_id = f"test-outbox-tenant-{uuid.uuid4().hex[:8]}"

    # Setup Tenant
    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name=f"Test Tenant {uuid.uuid4().hex[:8]}",
            slug=tenant_id,
            status="ACTIVE",
        )
        session.add(tenant)

    repo = SqlAlchemyNotificationOutboxRepository(db_session_factory)

    # Save
    event = NotificationOutboxEvent(
        tenant_id=tenant_id,
        event_type="test.event",
        payload={"msg": "hello"},
        idempotency_key="idemp_123",
    )

    await repo.save(event)

    # Fetch
    events = await repo.claim_next_events(worker_id="test_worker", limit=10, lock_lease_ms=5000)
    assert len(events) >= 1

    fetched = next((e for e in events if e.idempotency_key == "idemp_123"), None)
    assert fetched is not None
    assert fetched.payload == {"msg": "hello"}

    # Mark processed
    await repo.mark_completed(fetched.id, worker_id="test_worker")

    # Fetch again, should not return processed
    events2 = await repo.claim_next_events(worker_id="test_worker", limit=10, lock_lease_ms=5000)
    fetched2 = next((e for e in events2 if e.idempotency_key == "idemp_123"), None)
    assert fetched2 is None


@pytest.mark.asyncio
async def test_outbox_mark_failed_and_sweep(db_session_factory):
    tenant_id = f"test-outbox-tenant-{uuid.uuid4().hex[:8]}"

    # Setup Tenant
    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name=f"Test Tenant {uuid.uuid4().hex[:8]}",
            slug=tenant_id,
            status="ACTIVE",
        )
        session.add(tenant)

    repo = SqlAlchemyNotificationOutboxRepository(db_session_factory)
    event = NotificationOutboxEvent(
        tenant_id=tenant_id,
        event_type="test.fail",
        payload={"msg": "fail"},
        idempotency_key="idemp_fail",
    )
    await repo.save(event)

    # Claim
    events = await repo.claim_next_events(worker_id="fail_worker", limit=10, lock_lease_ms=5000)
    fetched = next((e for e in events if e.idempotency_key == "idemp_fail"), None)
    assert fetched is not None

    # Mark failed 1st time
    await repo.mark_failed(fetched.id, worker_id="fail_worker", error_reason="error1")

    # Claim again - should be available because it was marked PENDING after failure
    events2 = await repo.claim_next_events(worker_id="fail_worker", limit=10, lock_lease_ms=5000)
    fetched2 = next((e for e in events2 if e.idempotency_key == "idemp_fail"), None)
    assert fetched2 is not None

    # Mark failed 2nd time
    await repo.mark_failed(fetched2.id, worker_id="fail_worker", error_reason="error2")

    # Claim again
    events3 = await repo.claim_next_events(worker_id="fail_worker", limit=10, lock_lease_ms=5000)
    fetched3 = next((e for e in events3 if e.idempotency_key == "idemp_fail"), None)
    assert fetched3 is not None

    # Mark failed 3rd time (max attempts = 3, so it should go to FAILED state)
    await repo.mark_failed(fetched3.id, worker_id="fail_worker", error_reason="error3")

    # Claim again - should NOT be available because it's FAILED
    events4 = await repo.claim_next_events(worker_id="fail_worker", limit=10, lock_lease_ms=5000)
    fetched4 = next((e for e in events4 if e.idempotency_key == "idemp_fail"), None)
    assert fetched4 is None

    # Sweep stuck events test
    # Save a new event
    event_sweep = NotificationOutboxEvent(
        tenant_id=tenant_id,
        event_type="test.sweep",
        payload={"msg": "sweep"},
        idempotency_key="idemp_sweep",
    )
    await repo.save(event_sweep)

    # Claim but let lock expire (simulate lock_lease_ms = 0 so it expires immediately)
    events_sweep = await repo.claim_next_events(worker_id="sweep_worker", limit=10, lock_lease_ms=0)
    fetched_sweep = next((e for e in events_sweep if e.idempotency_key == "idemp_sweep"), None)
    assert fetched_sweep is not None

    # Sweep
    swept = await repo.sweep_stuck_events(lock_lease_ms=0)
    assert swept >= 1

    # Should be claimable again
    events_sweep2 = await repo.claim_next_events(
        worker_id="sweep_worker2", limit=10, lock_lease_ms=5000
    )
    fetched_sweep2 = next((e for e in events_sweep2 if e.idempotency_key == "idemp_sweep"), None)
    assert fetched_sweep2 is not None


@pytest.mark.asyncio
async def test_sqlalchemy_notification_outbox_publisher(db_session_factory):
    from notification.adapters.outbound.database.postgres_outbox_repository import (
        SqlAlchemyNotificationOutboxPublisher,
    )

    tenant_id = f"test-pub-tenant-{uuid.uuid4().hex[:8]}"

    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name=f"Test Tenant {uuid.uuid4().hex[:8]}",
            slug=tenant_id,
            status="ACTIVE",
        )
        session.add(tenant)

        publisher = SqlAlchemyNotificationOutboxPublisher(session)
        event = NotificationOutboxEvent(
            tenant_id=tenant_id,
            event_type="test.publish",
            payload={"pub": "msg"},
            idempotency_key="idemp_pub",
        )
        await publisher.save(event)

    # Verify it was saved
    repo = SqlAlchemyNotificationOutboxRepository(db_session_factory)
    events = await repo.claim_next_events(worker_id="test_worker", limit=10, lock_lease_ms=5000)
    fetched = next((e for e in events if e.idempotency_key == "idemp_pub"), None)
    assert fetched is not None
