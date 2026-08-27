from types import SimpleNamespace
from typing import Any

import pytest

from edi.adapters.outbound.database.postgres_data_plane_outbox_repository import (
    SqlAlchemyDataPlaneOutboxRepository,
)


class _Result:
    def __init__(self, rows: list[Any] | None = None, rowcount: int = 1) -> None:
        self.rows = rows or []
        self.rowcount = rowcount

    def __iter__(self):
        return iter(self.rows)


class _RetrySession:
    def __init__(self, owner_token: str) -> None:
        self.status = "PROCESSING"
        self.owner_token: str | None = owner_token
        self.attempts = 0

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "SET status = 'PENDING', attempts = attempts + 1" in sql:
            assert params["worker_id"] == self.owner_token
            self.status = "PENDING"
            self.owner_token = None
            self.attempts += 1
            return _Result()
        if "RETURNING *" in sql:
            assert self.status == "PENDING"
            self.status = "PROCESSING"
            self.owner_token = params["worker_id"]
            row = SimpleNamespace(
                _mapping={
                    "id": "event-1",
                    "tenant_id": "tenant-1",
                    "event_type": "test.event",
                    "payload": {},
                    "idempotency_key": "key-1",
                }
            )
            return _Result([row])

        assert self.status == "PROCESSING"
        self.status = "PROCESSED"
        self.owner_token = None
        return _Result()

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_failed_publish_can_be_claimed_again_and_completed():
    session = _RetrySession("worker-1")
    repository = SqlAlchemyDataPlaneOutboxRepository(session)

    await repository.mark_failed("event-1", "worker-1", "temporary failure")
    retried_events = await repository.claim_next_events("worker-2", limit=1)
    await repository.mark_completed(retried_events[0].id, "worker-2")

    assert session.attempts == 1
    assert session.status == "PROCESSED"
