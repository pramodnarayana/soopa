import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from database.models.pubsub import PlatformQueueMessage
from database.models.scheduling import ScheduledJob
from database.provider import get_async_engine
from outbox.domain.constants import OutboxStatus
from scheduler.domain.constants import JobStatus
from seedwork import generate_random_hex
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from scheduler_worker.bootstrap.container import Container
from scheduler_worker.config.settings import get_settings

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(scope="session")
def event_loop() -> AsyncGenerator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_engine() -> AsyncGenerator[AsyncEngine]:
    db_url = get_settings().database_url
    engine = get_async_engine(db_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_connection(db_engine: AsyncEngine) -> AsyncGenerator[AsyncConnection]:
    connection = await db_engine.connect()
    transaction = await connection.begin()
    yield connection
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture(scope="function")
async def db_session_factory(
    db_connection: AsyncConnection,
) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    factory = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )
    yield factory


async def test_scheduler_worker_claims_and_dispatches_job(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # 1. Seed an isolated namespace-scoped pending job via SQLAlchemy ORM (zero raw SQL / DELETE)
    suffix = generate_random_hex(6)
    job_id = f"job_{suffix}"
    test_namespace = f"scheduler_integration_{suffix}"
    queue_name = f"edi-data-plane-jobs-{suffix}.fifo"
    queue_uri = f"db://{queue_name}"

    async with db_session_factory() as session:
        session.add(
            ScheduledJob(
                id=job_id,
                name="Integration_Test_Job",
                payload={"test_key": "test_value"},
                status=JobStatus.PENDING.value,
                next_run_at=datetime.now(UTC),
                target_queue=queue_name,
                app_namespace=test_namespace,
                retry_count=0,
                max_retries=3,
            )
        )
        await session.commit()

    # 2. Wire Container with real PostgreSQL DatabaseJobDispatcher scoped to test_namespace
    container = Container()
    container.config.active_namespaces.from_value([test_namespace])
    container.session_factory.override(db_session_factory)
    container.job_dispatcher.add_kwargs(queue_url_map={queue_name: queue_uri})
    container.wire()

    # 3. Execute the Claim Use Case (mimics what the SchedulerPoller does)
    claim_use_case = container.claim_use_case()
    await claim_use_case.execute(worker_id="test_worker_1", limit=1, lock_lease_ms=1000)

    # 4. Verify Job Status & Sovereign PostgreSQL Queue Row via SQLAlchemy ORM
    async with db_session_factory() as session:
        job_row = (
            await session.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
        ).scalar_one_or_none()
        assert job_row is not None
        assert job_row.status == JobStatus.COMPLETED.value

        queue_rows = list(
            (
                await session.execute(
                    select(PlatformQueueMessage).where(
                        PlatformQueueMessage.queue_name == queue_name
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(queue_rows) == 1, "No message was dispatched to pubsub.platform_queue_messages"
    msg = queue_rows[0]
    assert msg.status == OutboxStatus.PENDING.value
    assert msg.payload["job_id"] == job_id
    assert isinstance(msg.payload["payload"], dict)
    assert msg.payload["payload"]["test_key"] == "test_value"
