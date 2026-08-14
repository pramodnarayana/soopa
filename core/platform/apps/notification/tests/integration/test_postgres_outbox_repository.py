import pytest
from platform_orm.models.identity import Tenant

from notification.adapters.outbound.postgres_outbox_repository import (
    PostgresOutboxRepository,
)
from notification.domain.models import NotificationOutboxEvent


@pytest.mark.asyncio
async def test_outbox_save_and_fetch(db_session_factory):
    tenant_id = "test-outbox-tenant"

    # Setup Tenant
    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name="Test Tenant",
            slug=tenant_id,
            status="ACTIVE",
        )
        session.add(tenant)

    repo = PostgresOutboxRepository(db_session_factory)

    # Save
    event = NotificationOutboxEvent(
        tenant_id=tenant_id,
        event_type="test.event",
        payload={"msg": "hello"},
        idempotency_key="idemp_123",
    )

    await repo.save(event)

    # Fetch
    events = await repo.claim_next_messages(worker_id="test_worker", limit=10, lock_lease_ms=5000)
    assert len(events) >= 1

    fetched = next((e for e in events if e.idempotency_key == "idemp_123"), None)
    assert fetched is not None
    assert fetched.payload == {"msg": "hello"}

    # Mark processed
    await repo.mark_completed(fetched.id, worker_id="test_worker")

    # Fetch again, should not return processed
    events2 = await repo.claim_next_messages(worker_id="test_worker", limit=10, lock_lease_ms=5000)
    fetched2 = next((e for e in events2 if e.idempotency_key == "idemp_123"), None)
    assert fetched2 is None
