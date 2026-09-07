from datetime import UTC, datetime, timedelta

import pytest
from config_sync_worker.adapters.outbound.database.postgres_edi_control_plane_outbox_repository import (
    PostgresEdiControlPlaneOutboxRepository,
)
from database.router import DatabaseRouterPort
from edi.domain.enums import EdiEventType
from edi.testing.factories.outbox import ControlPlaneOutboxBuilder
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from outbox.domain.constants import OutboxStatus
from pubsub.testing.in_memory_event_bus import InMemoryEventBus

pytestmark = pytest.mark.integration


@pytest.mark.integration
async def test_cp_sweeper_fetches_and_processes_events(db_router: DatabaseRouterPort):
    # 1. Setup Data - stuck events that need sweeping
    async for test_session in db_router.get_global_session():
        builder = ControlPlaneOutboxBuilder(session=test_session)
        event1 = await builder.create(
            event_type=EdiEventType.edi_as2_partner_created.value, status=OutboxStatus.PROCESSING
        )
        event2 = await builder.create(
            event_type=EdiEventType.edi_as2_partner_updated.value, status=OutboxStatus.PROCESSING
        )

        event1.lease_expires_at = datetime.now(UTC) - timedelta(minutes=10)
        event2.lease_expires_at = datetime.now(UTC) - timedelta(minutes=10)

        await test_session.commit()

    # 2. Use InMemoryEventBus test infra
    event_bus = InMemoryEventBus()
    repo = PostgresEdiControlPlaneOutboxRepository(db_router=db_router)

    use_case = OutboxSweeperUseCase(repository=repo, publisher=event_bus)

    # 3. Execute Sweeper
    await use_case.execute()

    # 4. Verify by polling the in memory event bus
    messages_received = []

    async with event_bus.poll_raw_message() as msg1:
        if msg1:
            messages_received.append(msg1.payload)
            await msg1.ack()

    async with event_bus.poll_raw_message() as msg2:
        if msg2:
            messages_received.append(msg2.payload)
            await msg2.ack()

    assert len(messages_received) == 2

    assert any(
        b.get("event_type") == EdiEventType.edi_as2_partner_created.value for b in messages_received
    )
    assert any(
        b.get("event_type") == EdiEventType.edi_as2_partner_updated.value for b in messages_received
    )
