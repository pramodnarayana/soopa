from datetime import UTC, datetime, timedelta

import pytest
from database.router import DatabaseRouterPort
from edi.domain.enums import PipelineEventType
from edi.testing.factories.outbox import DataPlaneOutboxBuilder
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from outbox.domain.constants import OutboxStatus
from pubsub.testing.in_memory_event_bus import InMemoryEventBus

from edi_dp_outbox_worker.adapters.outbound.database.postgres_edi_data_plane_outbox_repository import (
    PostgresEdiDataPlaneOutboxRepository,
)

pytestmark = pytest.mark.integration


@pytest.mark.integration
async def test_sweeper_fetches_and_processes_events(db_router: DatabaseRouterPort):
    # 1. Setup Data - stuck events that need sweeping
    async for test_session in db_router.get_shard_session("ucp_shard_1", "fake_dsn"):
        builder = DataPlaneOutboxBuilder(session=test_session)
        # We will create events with default properties that makes them look "stuck".
        event1 = await builder.create(
            event_type=PipelineEventType.TRANSFORM_EVENT.value, status=OutboxStatus.PROCESSING
        )
        event2 = await builder.create(
            event_type=PipelineEventType.DELIVER_EVENT.value, status=OutboxStatus.PROCESSING
        )

        # Manually force them to be "stuck" by setting lease_expires_at to the past
        event1.lease_expires_at = datetime.now(UTC) - timedelta(minutes=10)
        event2.lease_expires_at = datetime.now(UTC) - timedelta(minutes=10)

        await test_session.commit()

    # 2. Use InMemoryEventBus test infra
    event_bus = InMemoryEventBus()
    repo = PostgresEdiDataPlaneOutboxRepository(db_router=db_router)

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
        b.get("event_type") == PipelineEventType.TRANSFORM_EVENT.value for b in messages_received
    )
    assert any(
        b.get("event_type") == PipelineEventType.DELIVER_EVENT.value for b in messages_received
    )
