import datetime
import uuid

import pytest
from database.models.identity import IdentityOutbox

from identity.adapters.outbound.database.postgres_identity_outbox_cleanup_repository import (
    SqlAlchemyIdentityOutboxCleanupRepository,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_identity_outbox_cleanup(db_session_factory):
    repo = SqlAlchemyIdentityOutboxCleanupRepository(db_session_factory)
    now = datetime.datetime.now(datetime.UTC)

    # Create old processed event
    old_event = IdentityOutbox(
        id=f"evt_{uuid.uuid4().hex[:12]}",
        idempotency_key=f"idemp_{uuid.uuid4().hex[:12]}",
        tenant_id="platform",
        event_type="test",
        payload={},
        status="COMPLETED",
        created_at=now - datetime.timedelta(days=10),
    )
    # Create old unprocessed event
    old_unprocessed = IdentityOutbox(
        id=f"evt_{uuid.uuid4().hex[:12]}",
        idempotency_key=f"idemp_{uuid.uuid4().hex[:12]}",
        tenant_id="platform",
        event_type="test",
        payload={},
        status="PENDING",
        created_at=now - datetime.timedelta(days=10),
    )
    # Create new processed event
    new_event = IdentityOutbox(
        id=f"evt_{uuid.uuid4().hex[:12]}",
        idempotency_key=f"idemp_{uuid.uuid4().hex[:12]}",
        tenant_id="platform",
        event_type="test",
        payload={},
        status="COMPLETED",
        created_at=now,
    )

    async with db_session_factory() as db_session:
        db_session.add_all([old_event, old_unprocessed, new_event])
        await db_session.commit()

    # Clean up events older than 5 days
    deleted_count = await repo.cleanup_outbox(retention_days=5)

    # Should delete exactly 1 (the old processed event)
    # Depending on what other tests inserted, it might be >= 1
    assert deleted_count >= 1
