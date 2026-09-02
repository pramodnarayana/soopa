import asyncio
import json
import os
from collections.abc import AsyncGenerator
from typing import Any

import boto3
import pytest
import pytest_asyncio
from database.provider import get_async_engine
from seedwork import generate_random_hex
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scheduler_worker.bootstrap.container import Container


@pytest.fixture(scope="session")
def event_loop() -> AsyncGenerator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def localstack_container() -> dict[str, str]:
    endpoint_url = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")

    sqs_client = boto3.client(
        "sqs",
        endpoint_url=endpoint_url,
        region_name="us-east-1",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
    )

    unique_suffix = generate_random_hex(6)
    queue_name = f"edi-data-plane-jobs-{unique_suffix}.fifo"

    queue = sqs_client.create_queue(
        QueueName=queue_name,
        Attributes={"FifoQueue": "true", "ContentBasedDeduplication": "true"},
    )

    return {
        "endpoint_url": endpoint_url,
        "sqs_queue_url": queue["QueueUrl"],
        "sqs_queue_name": queue_name,
    }


@pytest_asyncio.fixture(scope="function")
async def db_engine() -> AsyncGenerator[Any]:
    db_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
    )
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = get_async_engine(db_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_connection(db_engine) -> AsyncGenerator[Any]:
    connection = await db_engine.connect()
    transaction = await connection.begin()
    yield connection
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture(scope="function")
async def db_session_factory(db_connection) -> AsyncGenerator[async_sessionmaker]:
    factory = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )
    yield factory


@pytest.mark.asyncio
@pytest.mark.integration
async def test_scheduler_worker_claims_and_dispatches_job(
    db_connection: Any, db_session_factory: async_sessionmaker, localstack_container: dict[str, str]
) -> None:
    # 1. Setup DB Data (A pending job)
    job_id = f"job_{generate_random_hex(6)}"
    queue_name = localstack_container["sqs_queue_name"]

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

    # 2. Setup Container
    os.environ["AWS_ENDPOINT_URL"] = localstack_container["endpoint_url"]
    os.environ["AWS_REGION"] = "us-east-1"
    os.environ["SQS_DATA_PLANE_JOBS_QUEUE_URL"] = localstack_container["sqs_queue_url"]

    container = Container()
    container.session_factory.override(db_session_factory)

    # We dynamically mock the JobDispatcher map inside the provider because SQSJobDispatcher is strict about queue urls
    container.job_dispatcher.add_kwargs(
        queue_url_map={queue_name: localstack_container["sqs_queue_url"]}
    )

    container.wire()

    # 3. Execute the Claim Use Case (mimics what the Poller does)
    claim_use_case = container.claim_use_case()
    await claim_use_case.execute(worker_id="test_worker_1", limit=1, lock_lease_ms=1000)

    # 4. Verify DB Status
    async with db_session_factory() as session:
        res = await session.execute(
            text("SELECT status FROM scheduling.scheduled_jobs WHERE id = :id"), {"id": job_id}
        )
        status = res.scalar_one_or_none()

    assert status == "COMPLETED", f"Expected job status COMPLETED, got {status}"

    # 5. Verify SQS Queue Received Message
    sqs_client = boto3.client(
        "sqs",
        endpoint_url=localstack_container["endpoint_url"],
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",  # noqa: S106
    )

    response = sqs_client.receive_message(
        QueueUrl=localstack_container["sqs_queue_url"], MaxNumberOfMessages=1, WaitTimeSeconds=2
    )

    messages = response.get("Messages", [])
    assert len(messages) == 1, "No message was dispatched to the SQS queue"

    body = json.loads(messages[0]["Body"])
    assert body["job_id"] == job_id
    assert body["payload"]["test_key"] == "test_value"
