from unittest.mock import AsyncMock

import pytest
from platform_orm.events import EventEnvelope

from edi_background_worker.adapters.outbound.database.postgres_edi_data_plane_outbox_cleanup_repository import (
    SqlAlchemyEdiDataPlaneOutboxCleanupRepository,
)
from edi_background_worker.adapters.outbound.database.postgres_edi_data_plane_outbox_repository import (
    PostgresEdiDataPlaneOutboxRepository,
)


def _event(event_id: str) -> EventEnvelope:
    return EventEnvelope(
        id=event_id,
        source="edi_data_plane",
        event_type="TRANSFORM_EVENT",
        tenant_id="tenant-1",
        idempotency_key=event_id,
        payload={},
    )


@pytest.mark.asyncio
async def test_claim_next_events_collects_events_from_two_tenant_shards():
    router = AsyncMock()
    router.get_all_shards.return_value = [("shard-1", "dsn-1"), ("shard-2", "dsn-2")]
    repository = PostgresEdiDataPlaneOutboxRepository(router)
    repository._claim_from_shard = AsyncMock(side_effect=[[_event("event-1")], [_event("event-2")]])

    events = await repository.claim_next_events("worker-1", limit=2)

    assert [event.id for event in events] == ["event-1", "event-2"]
    assert [call.args[0] for call in repository._claim_from_shard.await_args_list] == [
        "shard-1",
        "shard-2",
    ]
    router.get_global_session.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["mark_completed", "mark_failed"])
async def test_status_updates_are_routed_to_all_tenant_shards(operation):
    router = AsyncMock()
    repository = PostgresEdiDataPlaneOutboxRepository(router)
    repository._update_all_shards = AsyncMock()

    if operation == "mark_completed":
        await repository.mark_completed("event-1", "worker-1")
    else:
        await repository.mark_failed("event-1", "worker-1", "failed")

    repository._update_all_shards.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_returns_deleted_count_aggregated_across_shards(monkeypatch):
    class FakeSession:
        rowcounts = iter([2, 3])

        def __init__(self, *args, **kwargs):
            self.rowcount = next(self.rowcounts)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement):
            result = AsyncMock()
            result.rowcount = self.rowcount
            return result

        async def commit(self):
            return None

    monkeypatch.setattr(
        "edi_background_worker.adapters.outbound.database."
        "postgres_edi_data_plane_outbox_cleanup_repository.AsyncSession",
        FakeSession,
    )
    router = AsyncMock()
    router.get_all_shards.return_value = [("shard-1", "dsn-1"), ("shard-2", "dsn-2")]
    router.get_engine.side_effect = [object(), object()]
    repository = SqlAlchemyEdiDataPlaneOutboxCleanupRepository(router)

    deleted = await repository.cleanup_outbox(retention_days=30)

    assert deleted == 5
