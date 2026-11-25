import asyncio
import json
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from database.provider import get_async_engine
from seedwork import generate_random_hex
from sqlalchemy import text
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


@pytest_asyncio.fixture(autouse=True, scope="function")
async def clear_jobs_table(db_connection: AsyncConnection) -> None:
    """Ensure each test starts with an empty jobs table, avoiding conflicts with seed data."""
    await db_connection.execute(text("DELETE FROM scheduling.scheduled_jobs"))


async def test_scheduler_worker_claims_and_dispatches_job(
    db_connection: AsyncConnection,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # 1. Setup DB Data (A pending job targeting a sovereign PostgreSQL queue)
    job_id = f"job_{generate_random_hex(6)}"
    queue_name = f"edi-data-plane-jobs-{generate_random_hex(6)}.fifo"
    queue_uri = f"db://{queue_name}"

    await db_connection.execute(
        text("""
            INSERT INTO scheduling.scheduled_jobs
            (id, name, payload, status, next_run_at, target_queue, retry_count, max_retries, created_at, updated_at)
            VALUES (:id, :name, :payload, 'PENDING', NOW(), :queue, 0, 3, NOW(), NOW())
        """),
        {
            "id": job_id,
            "name": "Integration_Test_Job",
            "payload": json.dumps({"test_key": "test_value"}),
            "queue": queue_name,
        },
    )
    await db_connection.execute(text("SAVEPOINT seed_complete"))

    # 2. Setup Container with real PostgreSQL DatabaseJobDispatcher
    container = Container()
    container.session_factory.override(db_session_factory)
    container.job_dispatcher.add_kwargs(queue_url_map={queue_name: queue_uri})
    container.wire()

    # 3. Execute the Claim Use Case (mimics what the Poller does)
    claim_use_case = container.claim_use_case()
    await claim_use_case.execute(worker_id="test_worker_1", limit=1, lock_lease_ms=1000)

    # 4. Verify Job Status & Sovereign PostgreSQL Queue Row
    async with db_session_factory() as session:
        res = await session.execute(
            text("SELECT status FROM scheduling.scheduled_jobs WHERE id = :id"), {"id": job_id}
        )
        status = res.scalar_one_or_none()
        assert status == "COMPLETED", f"Expected job status COMPLETED, got {status}"

        queue_res = await session.execute(
            text("""
                SELECT payload, status
                FROM pubsub.platform_queue_messages
                WHERE queue_name = :queue_name
            """),
            {"queue_name": queue_name},
        )
        rows = queue_res.fetchall()

    assert len(rows) == 1, "No message was dispatched to pubsub.platform_queue_messages"
    body, msg_status = rows[0]
    assert msg_status == "PENDING"
    assert body["job_id"] == job_id
    assert body["payload"]["test_key"] == "test_value"
