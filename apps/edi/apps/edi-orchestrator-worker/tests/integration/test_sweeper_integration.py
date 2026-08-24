import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.infrastructure import DatabaseShard

from worker.application.use_cases.edi_data_plane_outbox_sweeper_use_case import (
    EdiDataPlaneOutboxSweeperUseCase,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def db_router() -> "AsyncGenerator[DatabaseRouter, None]":
    # Use standard local environment DB URL
    global_url = os.getenv(
        "GLOBAL_DB_URL", "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_global"
    )
    router = DatabaseRouter(global_db_url=global_url)

    # Ensure shard exists
    async for session in router.get_global_session():
        from sqlalchemy import select

        res = await session.execute(select(DatabaseShard).where(DatabaseShard.name == "shard_1"))
        shard = res.scalars().first()
        if not shard:
            shard = DatabaseShard(
                id="test_shard_id",
                name="shard_1",
                dsn=os.getenv(
                    "SHARD_1_URL",
                    "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1",
                ),
            )
            session.add(shard)
            await session.commit()

    yield router
    await router.close_all()


@pytest.fixture
async def test_session(db_router: DatabaseRouter) -> "AsyncGenerator[AsyncSession, None]":
    shard_url = os.getenv(
        "SHARD_1_URL", "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"
    )
    engine = await db_router.get_engine("shard_1", shard_url)
    async with AsyncSession(engine) as session:
        # Cleanup before
        await session.execute(delete(DataPlaneOutbox))
        await session.commit()

        yield session

        # Cleanup after
        await session.execute(delete(DataPlaneOutbox))
        await session.commit()


@pytest.mark.integration
async def test_sweeper_fetches_and_processes_events(
    db_router: DatabaseRouter, test_session: AsyncSession
) -> None:
    # 1. Setup real DB records
    created_at = datetime.now(UTC) - timedelta(minutes=6)
    await test_session.execute(
        insert(DataPlaneOutbox).values(
            [
                {
                    "id": 1,
                    "event_type": "EDI_RECEIVED",
                    "payload": {},
                    "created_at": created_at,
                },
                {
                    "id": 2,
                    "event_type": "EDI_PROCESSED",
                    "payload": {},
                    "created_at": created_at,
                },
            ]
        )
    )
    await test_session.commit()

    # 2. Mock external SQS boundary (allowed by Enterprise Rules)
    mock_publisher = MagicMock()
    mock_publisher.publish_batch = AsyncMock(return_value=[])

    use_case = EdiDataPlaneOutboxSweeperUseCase(
        db_router=db_router, message_publisher=mock_publisher
    )

    # Mock processor to simulate successfully processing the batch
    use_case.processor.process_batch = AsyncMock(return_value=2)

    # 3. Execute Sweeper against real local DB
    processed = await use_case.execute()

    # 4. Verify
    assert processed >= 2
    use_case.processor.process_batch.assert_called_once()
