from datetime import UTC, datetime, timedelta

import pytest
from database.router import DatabaseRouter
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from outbox.domain.constants import OutboxStatus
from sqlalchemy import select

from edi_dp_jobs_worker.adapters.outbound.database.sqlalchemy_edi_data_plane_outbox_sweeper_repository import (
    SqlAlchemyEdiDataPlaneOutboxSweeperRepository,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def sweeper_repo(
    db_router: DatabaseRouter,
) -> SqlAlchemyEdiDataPlaneOutboxSweeperRepository:
    return SqlAlchemyEdiDataPlaneOutboxSweeperRepository(db_router)


async def test_sweep_stuck_events(
    sweeper_repo: SqlAlchemyEdiDataPlaneOutboxSweeperRepository,
    db_router: DatabaseRouter,
) -> None:
    tenant_id = "test_tenant_sweep"
    now = datetime.now(UTC)

    # Event 1: PENDING (SHOULD NOT BE SWEPT)
    evt1 = DataPlaneOutbox(
        tenant_id=tenant_id,
        idempotency_key="evt1",
        event_type="TEST",
        payload={"id": "evt1"},
        status=OutboxStatus.PENDING.value,
        lease_expires_at=None,
    )

    # Event 2: PROCESSING, lease expired (SHOULD BE SWEPT)
    evt2 = DataPlaneOutbox(
        tenant_id=tenant_id,
        idempotency_key="evt2",
        event_type="TEST",
        payload={"id": "evt2"},
        status=OutboxStatus.PROCESSING.value,
        lease_expires_at=now - timedelta(minutes=5),
        owner_token="some-worker",
    )

    # Event 3: PROCESSING, lease active (SHOULD NOT BE SWEPT)
    evt3 = DataPlaneOutbox(
        tenant_id=tenant_id,
        idempotency_key="evt3",
        event_type="TEST",
        payload={"id": "evt3"},
        status=OutboxStatus.PROCESSING.value,
        lease_expires_at=now + timedelta(minutes=5),
        owner_token="some-worker",
    )

    shards = await db_router.get_all_shards()
    async for session in db_router.get_shard_session(shards[0][0], shards[0][1]):
        session.add_all([evt1, evt2, evt3])
        await session.commit()

    try:
        # Run sweep
        swept_count = await sweeper_repo.sweep_stuck_events()
        assert swept_count >= 1

        # Check DB
        async for session in db_router.get_shard_session(shards[0][0], shards[0][1]):
            result = await session.execute(
                select(DataPlaneOutbox).where(DataPlaneOutbox.tenant_id == tenant_id)
            )
            rows = result.scalars().all()

            by_id = {r.idempotency_key: r for r in rows}
            assert by_id["evt1"].status == OutboxStatus.PENDING.value
            assert by_id["evt2"].status == OutboxStatus.PENDING.value
            assert by_id["evt2"].owner_token is None
            assert by_id["evt3"].status == OutboxStatus.PROCESSING.value
            assert by_id["evt3"].owner_token == "some-worker"

    finally:
        # Cleanup
        async for session in db_router.get_shard_session(shards[0][0], shards[0][1]):
            result = await session.execute(
                select(DataPlaneOutbox).where(DataPlaneOutbox.tenant_id == tenant_id)
            )
            for item in result.scalars():
                await session.delete(item)
            await session.commit()
