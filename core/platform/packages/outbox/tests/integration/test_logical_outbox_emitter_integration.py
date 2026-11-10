from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from database.provider import get_async_engine
from database.testing import assert_test_database_url
from outbox.adapters.outbound.sqlalchemy_logical_outbox_emitter import (
    SqlAlchemyLogicalOutboxEmitter,
)
from outbox.domain.constants import LogicalOutboxChannel
from seedwork.events import EventEnvelope, EventProcessingLane
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


@pytest.fixture
async def isolated_db_session() -> AsyncGenerator[AsyncSession, None]:
    db_url = assert_test_database_url(os.environ["DATABASE_URL"])
    engine = get_async_engine(db_url, statement_cache_size=0)
    async with engine.connect() as conn:
        outer_tx = await conn.begin()
        try:
            factory = async_sessionmaker(
                bind=conn,
                class_=AsyncSession,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            async with factory() as session:
                yield session
        finally:
            if outer_tx.is_active:
                await outer_tx.rollback()
    await engine.dispose()


@pytest.mark.integration
async def test_logical_outbox_emitter_advances_real_postgres_wal_lsn(
    isolated_db_session: AsyncSession,
) -> None:
    emitter = SqlAlchemyLogicalOutboxEmitter(
        session=isolated_db_session,
        channel=LogicalOutboxChannel.SOOPA_OUTBOX,
    )
    suffix = os.urandom(12).hex()
    e1 = EventEnvelope(
        id=f"evt_{suffix}_1",
        source="soopa.consumer",
        event_type="checkout.completed",
        tenant_id=f"iam_ten_{suffix}",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={"amount_cents": 4900},
        lane=EventProcessingLane.REALTIME,
    )
    e2 = EventEnvelope(
        id=f"evt_{suffix}_2",
        source="soopa.consumer",
        event_type="loyalty.credited",
        tenant_id=f"iam_ten_{suffix}",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={"points": 49},
        lane=EventProcessingLane.REALTIME,
    )

    first_res = await emitter.emit_transactional_batch([e1])
    second_res = await emitter.emit_transactional_batch([e2])

    assert first_res.emitted_count == 1
    assert second_res.emitted_count == 1
    assert first_res.high_watermark is not None
    assert second_res.high_watermark is not None
    assert second_res.high_watermark > first_res.high_watermark
