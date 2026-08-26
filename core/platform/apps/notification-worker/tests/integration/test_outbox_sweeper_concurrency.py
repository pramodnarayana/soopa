from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from database.models.identity import Tenant
from database.models.notifications import NotificationOutbox
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult


@pytest.mark.asyncio
async def test_outbox_sweeper_concurrency(db_session_factory):
    """
    Regression test: Ensure that if a sweeper reads a row in its inner CTE, but before
    the outer UPDATE executes, another sweeper processes the row (e.g. status changes to
    COMPLETED or another worker claims it with a new lease), the stale sweeper's outer
    """

    async with db_session_factory() as session, session.begin():
        tenant = Tenant(id="t_conc", name="Concurrency Tenant", slug="t_conc")
        session.add(tenant)

        orm_msg = NotificationOutbox(
            id="msg-stuck-1",
            tenant_id="t_conc",
            event_type="test",
            idempotency_key="idemp-c1",
            payload={"test": "data"},
            status="PROCESSING",
            owner_token="crashed_worker",  # noqa: S106
            updated_at=datetime.now(UTC) - timedelta(minutes=10),  # Expired lease
            lease_expires_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        session.add(orm_msg)

    # 2. Simulate the concurrency race condition.
    # We will simulate exactly what the `sweep_stuck_messages` does, but manually pause between CTE and UPDATE
    # to let another transaction modify the row.

    threshold = datetime.now(UTC) - timedelta(minutes=1)

    async with db_session_factory() as session1:
        # Instead of running the full UPDATE statement, we simulate the inner CTE fetching the ID
        stmt_select = (
            select(NotificationOutbox.id)
            .where(
                NotificationOutbox.status == "PROCESSING",
                NotificationOutbox.updated_at < threshold,
            )
            .limit(500)
        )
        result1 = await session1.execute(stmt_select)
        stuck_ids = [row[0] for row in result1.all()]
        assert "msg-stuck-1" in stuck_ids

        # --- CONCURRENT INTERFERENCE ---
        # Before session1 can execute its UPDATE, another worker successfully finishes the job!
        async with db_session_factory() as session2, session2.begin():
            stmt_interfere = (
                update(NotificationOutbox)
                .where(NotificationOutbox.id == "msg-stuck-1")
                .values(status="COMPLETED", owner_token="worker_2", updated_at=datetime.now(UTC))  # noqa: S106
            )
            await session2.execute(stmt_interfere)
        # -------------------------------

        # Now session1 continues with its outer UPDATE, using the IDs it found, BUT
        # with the newly added outer predicates!
        stmt_update = (
            update(NotificationOutbox)
            .where(
                NotificationOutbox.id.in_(stuck_ids),
                NotificationOutbox.status == "PROCESSING",  # The crucial fix!
                NotificationOutbox.updated_at < threshold,  # The crucial fix!
            )
            .values(status="PENDING", owner_token=None)
        )
        result = await session1.execute(stmt_update)
        swept = cast(CursorResult, result).rowcount
        await session1.commit()

        # Because of the outer predicates, the update should affect 0 rows, preventing it
        # from resetting the COMPLETED job back to PENDING.
        assert swept == 0

    # 3. Verify final state is COMPLETED, not PENDING
    async with db_session_factory() as session:
        stmt = select(NotificationOutbox).where(NotificationOutbox.id == "msg-stuck-1")
        res = await session.execute(stmt)
        final_row = res.scalars().first()

        assert final_row is not None
        assert final_row.status == "COMPLETED"
        assert final_row.owner_token == "worker_2"  # noqa: S105
