import datetime

import pytest
from database.models.identity import IdentityOutbox
from outbox.adapters.outbound.sqlalchemy_global_outbox_repository import (
    SqlAlchemyGlobalOutboxRepository,
)
from outbox.domain.constants import OutboxStatus
from seedwork import generate_id

from identity.domain.constants import IdentityOutboxSource

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_identity_outbox_cleanup(db_session_factory):
    repo = SqlAlchemyGlobalOutboxRepository(
        session_factory=db_session_factory,
        model_cls=IdentityOutbox,
        source=IdentityOutboxSource.IDENTITY.value,
    )
    now = datetime.datetime.now(datetime.UTC)

    # Create old processed event
    old_event = IdentityOutbox(
        id=generate_id("evt"),
        idempotency_key=generate_id("idemp"),
        tenant_id="platform",
        event_type="test",
        payload={},
        status=OutboxStatus.COMPLETED,
        created_at=now - datetime.timedelta(days=10),
    )
    # Create old unprocessed event
    old_unprocessed = IdentityOutbox(
        id=generate_id("evt"),
        idempotency_key=generate_id("idemp"),
        tenant_id="platform",
        event_type="test",
        payload={},
        status=OutboxStatus.PENDING,
        created_at=now - datetime.timedelta(days=10),
    )
    # Create new processed event
    new_event = IdentityOutbox(
        id=generate_id("evt"),
        idempotency_key=generate_id("idemp"),
        tenant_id="platform",
        event_type="test",
        payload={},
        status=OutboxStatus.COMPLETED,
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
