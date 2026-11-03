import pytest
from database.models.identity import Tenant
from database.models.notifications import NotificationOutbox
from outbox.adapters.outbound.sqlalchemy_global_outbox_repository import (
    SqlAlchemyGlobalOutboxRepository,
)
from seedwork import generate_random_hex
from seedwork.events import EventEnvelope
from ucp.domain.constants import LifecycleStatus

from notification.adapters.outbound.database.sqlalchemy_outbox_repository import (
    SqlAlchemyNotificationOutboxRepository,
)
from notification.domain.constants import NotificationOutboxSource

pytestmark = pytest.mark.integration


def _build_global_outbox_repo(
    db_session_factory,
) -> SqlAlchemyGlobalOutboxRepository[NotificationOutbox]:
    return SqlAlchemyGlobalOutboxRepository(
        session_factory=db_session_factory,
        model_cls=NotificationOutbox,
        source=NotificationOutboxSource.NOTIFICATION.value,
    )


@pytest.mark.asyncio
async def test_outbox_save_and_fetch(db_session_factory) -> None:
    tenant_id = f"test-outbox-tenant-{generate_random_hex(6)}"

    event = EventEnvelope(
        id="fake_id_123",
        source=NotificationOutboxSource.NOTIFICATION.value,
        tenant_id=tenant_id,
        event_type="test.event",
        payload={"msg": "hello"},
        idempotency_key="idemp_123",
    )

    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name=f"Test Tenant {generate_random_hex(6)}",
            slug=tenant_id,
            status=LifecycleStatus.ACTIVE,
        )
        session.add(tenant)
        writer = SqlAlchemyNotificationOutboxRepository(session)
        await writer.save(event)
        # Duplicate save with identical idempotency_key must be a safe no-op
        await writer.save(event)

    repo = _build_global_outbox_repo(db_session_factory)

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
async def test_outbox_mark_failed_and_sweep(db_session_factory) -> None:
    tenant_id = f"test-outbox-tenant-{generate_random_hex(6)}"

    event = EventEnvelope(
        id="fake_id_456",
        source=NotificationOutboxSource.NOTIFICATION.value,
        tenant_id=tenant_id,
        event_type="test.fail",
        payload={"msg": "fail"},
        idempotency_key="idemp_fail",
    )

    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name=f"Test Tenant {generate_random_hex(6)}",
            slug=tenant_id,
            status=LifecycleStatus.ACTIVE,
        )
        session.add(tenant)
        writer = SqlAlchemyNotificationOutboxRepository(session)
        await writer.save(event)

    repo = _build_global_outbox_repo(db_session_factory)

    # Claim
    events = await repo.claim_next_events(worker_id="fail_worker", limit=10, lock_lease_ms=5000)
    fetched = next((e for e in events if e.idempotency_key == "idemp_fail"), None)
    assert fetched is not None

    # Mark failed 1st time
    await repo.mark_failed(fetched.id, worker_id="fail_worker", error_message="error1")

    # Claim again - should be available because it was marked PENDING after failure
    events2 = await repo.claim_next_events(worker_id="fail_worker", limit=10, lock_lease_ms=5000)
    fetched2 = next((e for e in events2 if e.idempotency_key == "idemp_fail"), None)
    assert fetched2 is not None

    # Mark failed 2nd time
    await repo.mark_failed(fetched2.id, worker_id="fail_worker", error_message="error2")

    # Claim again
    events3 = await repo.claim_next_events(worker_id="fail_worker", limit=10, lock_lease_ms=5000)
    fetched3 = next((e for e in events3 if e.idempotency_key == "idemp_fail"), None)
    assert fetched3 is not None

    # Mark failed 3rd time (max attempts = 3, so it should go to FAILED state)
    await repo.mark_failed(fetched3.id, worker_id="fail_worker", error_message="error3")

    # Claim again - should NOT be available because it's FAILED
    events4 = await repo.claim_next_events(worker_id="fail_worker", limit=10, lock_lease_ms=5000)
    fetched4 = next((e for e in events4 if e.idempotency_key == "idemp_fail"), None)
    assert fetched4 is None

    # Sweep stuck events test
    event_sweep = EventEnvelope(
        id="fake_id_789",
        source=NotificationOutboxSource.NOTIFICATION.value,
        tenant_id=tenant_id,
        event_type="test.sweep",
        payload={"msg": "sweep"},
        idempotency_key="idemp_sweep",
    )
    async with db_session_factory() as session, session.begin():
        writer = SqlAlchemyNotificationOutboxRepository(session)
        await writer.save(event_sweep)

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
