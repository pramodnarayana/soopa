from datetime import UTC, datetime, timedelta

import pytest
from database.router import DatabaseRouter
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox, ProcessedEvent
from edi.domain.enums import PipelineEventType

from edi_dp_jobs_worker.adapters.outbound.database.sqlalchemy_edi_data_plane_outbox_sweeper_repository import (
    SqlAlchemyEdiDataPlaneOutboxSweeperRepository,
)


@pytest.fixture
async def sweeper_repo(db_router: DatabaseRouter) -> SqlAlchemyEdiDataPlaneOutboxSweeperRepository:
    return SqlAlchemyEdiDataPlaneOutboxSweeperRepository(db_router)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_stranded_outbox_events(
    sweeper_repo: SqlAlchemyEdiDataPlaneOutboxSweeperRepository,
    db_router: DatabaseRouter,
) -> None:
    tenant_id = "test_tenant_sweep"
    now = datetime.now(UTC)

    # Event 1: Older than 5 mins, NO processed event (SHOULD BE SWEPT)
    evt1 = DataPlaneOutbox(
        tenant_id=tenant_id,
        idempotency_key="evt1",
        event_type=PipelineEventType.TRANSFORMATION_REQUESTED.value,
        payload={"id": "evt1"},
        created_at=now - timedelta(minutes=10),
    )

    # Event 2: Older than 5 mins, HAS processed event (SHOULD NOT BE SWEPT)
    evt2 = DataPlaneOutbox(
        tenant_id=tenant_id,
        idempotency_key="evt2",
        event_type=PipelineEventType.TRANSFORMATION_REQUESTED.value,
        payload={"id": "evt2"},
        created_at=now - timedelta(minutes=10),
    )
    proc2 = ProcessedEvent(
        tenant_id=tenant_id,
        idempotency_key="evt2",
    )

    # Event 3: Newer than 5 mins (in grace period), NO processed event (SHOULD NOT BE SWEPT)
    evt3 = DataPlaneOutbox(
        tenant_id=tenant_id,
        idempotency_key="evt3",
        event_type=PipelineEventType.TRANSFORMATION_REQUESTED.value,
        payload={"id": "evt3"},
        created_at=now - timedelta(minutes=2),
    )

    # Event 4: DELIVERY_SUCCESSFUL, older than grace period, NO processed event.
    # SHOULD BE SWEPT — the sweeper re-dispatches it to the orchestrator so the
    # state machine can transition. It is not a terminal event from the sweeper's
    # perspective; it is a stranded transition event.
    evt4 = DataPlaneOutbox(
        tenant_id=tenant_id,
        idempotency_key="evt4",
        event_type=PipelineEventType.DELIVERY_SUCCESSFUL.value,
        payload={"id": "evt4"},
        created_at=now - timedelta(minutes=10),
    )

    shards = await db_router.get_all_shards()
    async for session in db_router.get_shard_session(shards[0][0], shards[0][1]):
        session.add_all([evt1, evt2, evt3, evt4])
        session.add(proc2)
        await session.commit()

    try:
        # Run sweep
        swept = await sweeper_repo.fetch_stranded_outbox_events()

        # Filter for only this test's tenant to prevent cross-test pollution
        swept = [e for e in swept if e.tenant_id == tenant_id]
        swept_keys = {e.idempotency_key for e in swept}

        # Verify evt1 (TRANSFORMATION_REQUESTED, no processed event) is swept
        # and evt4 (DELIVERY_SUCCESSFUL, no processed event) is also swept.
        # evt2 is excluded (has a processed event), evt3 is excluded (in grace period).
        assert len(swept) == 2
        assert swept_keys == {"evt1", "evt4"}
    finally:
        # Cleanup
        async for session in db_router.get_shard_session(shards[0][0], shards[0][1]):
            for item in [evt1, evt2, evt3, evt4]:
                await session.delete(item)
            await session.delete(proc2)
            await session.commit()
