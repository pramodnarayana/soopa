"""Narrow PostgreSQL integration test for DatabaseJobDispatcher -> PlatformQueueMessage -> DirectOutboxConsumerManager."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

import pytest
from database.models.pubsub import PlatformQueueMessage
from database.provider import get_async_engine
from database.testing import assert_test_database_url
from pubsub.adapters.database.direct_outbox_consumer_manager import DirectOutboxConsumerManager
from pubsub.adapters.database.sqlalchemy_database_queue_repository import (
    SqlAlchemyDatabaseQueueRepository,
)
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from pubsub.provider import PubSubProvider
from seedwork.domain.types import JsonDict
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scheduler.adapters.outbound.messaging.database_job_dispatcher import DatabaseJobDispatcher
from scheduler.domain.constants import JobStatus
from scheduler.domain.scheduled_job import ScheduledJob

pytestmark = pytest.mark.integration

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@pytest.fixture
async def isolated_session_factory() -> AsyncGenerator[SessionFactory]:
    db_url = assert_test_database_url(os.environ["DATABASE_URL"])
    engine = get_async_engine(db_url, statement_cache_size=0)
    async with engine.connect() as conn:
        outer_tx = await conn.begin()
        try:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS pubsub"))
            await conn.run_sync(
                lambda sync_conn: PlatformQueueMessage.metadata.create_all(
                    sync_conn, checkfirst=True
                )
            )
            factory = async_sessionmaker(
                bind=conn,
                class_=AsyncSession,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            yield factory
        finally:
            if outer_tx.is_active:
                await outer_tx.rollback()
    await engine.dispose()


@pytest.mark.integration
async def test_database_job_dispatcher_enqueues_and_worker_drains_via_message_dispatcher(
    isolated_session_factory: SessionFactory,
) -> None:
    queue_name = f"sched_e2e_{os.urandom(6).hex()}"
    queue_uri = f"db://{queue_name}"
    queue_repo = SqlAlchemyDatabaseQueueRepository(session_factory=isolated_session_factory)
    dispatcher = DatabaseJobDispatcher(
        database_queue=queue_repo,
        queue_url_map={"ip-cp-jobs": queue_uri},
    )

    job = ScheduledJob(
        id=f"job_{os.urandom(4).hex()}",
        name="ip_control_plane_outbox_sweeper",
        target_queue="ip-cp-jobs",
        payload={"batch_size": 50},
        status=JobStatus.PENDING,
        cron_expression="* * * * *",
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=datetime.now(UTC),
        app_namespace="ip",
    )

    # Dispatch twice in same minute bucket -> idempotent deduplication inserts only 1 row
    await dispatcher.dispatch(job)
    await dispatcher.dispatch(job)

    async with isolated_session_factory() as session:
        count = (
            await session.execute(
                select(func.count())
                .select_from(PlatformQueueMessage)
                .where(PlatformQueueMessage.queue_name == queue_name)
            )
        ).scalar_one()
        assert count == 1

    received_payloads: list[JsonDict] = []
    job_dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

    async def handle_sweeper(msg: JsonDict) -> None:
        received_payloads.append(msg)

    job_dispatcher.subscribe("ip_control_plane_outbox_sweeper", handle_sweeper)

    consumer = PubSubProvider.create_consumer_manager(
        queue_uri,
        handler=job_dispatcher.dispatch,
        session_factory=isolated_session_factory,
    )
    assert isinstance(consumer, DirectOutboxConsumerManager)
    drained = await consumer.drain_once()
    assert drained == 1
    assert len(received_payloads) == 1
    assert received_payloads[0]["event_type"] == "job.ip_control_plane_outbox_sweeper.scheduled"
    nested = received_payloads[0]["payload"]
    assert isinstance(nested, dict)
    assert nested["job_id"] == job.id
    assert nested["job_name"] == "ip_control_plane_outbox_sweeper"
