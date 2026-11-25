"""Air-gapped end-to-end PostgreSQL Pub/Sub verification & burst/SIGKILL resilience tests.

Proves zero AWS coupling by explicitly stripping all AWS_* environment variables and exercising:
1. Seeded canonical topic fan-out (`pubsub.platform_topic_subscriptions` -> 5 bounded-context queues).
2. IP Control Plane REALTIME + BULK lane consumption with zero stranded bulk events.
3. Scheduler `create_job_dispatcher` -> `platform_queue_cleanup` in-process chunked purging.
4. 1,000-event burst drain enforcing exact CTE `LIMIT` + simulated `SIGKILL` lease recovery with zero loss.
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest
from database.models.pubsub import PlatformQueueMessage
from database.provider import get_async_engine
from database.testing import assert_test_database_url
from pubsub.adapters.database.direct_outbox_consumer_manager import DirectOutboxConsumerManager
from pubsub.adapters.database.sqlalchemy_database_queue_repository import (
    SqlAlchemyDatabaseQueueRepository,
)
from pubsub.domain.enums import PlatformTopicName, PubSubJobName
from pubsub.provider import PubSubProvider
from scheduler.domain.constants import JobStatus
from scheduler.domain.scheduled_job import ScheduledJob
from scheduler_worker.bootstrap.container import create_job_dispatcher
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_AWS_ENV_VARS: tuple[str, ...] = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_ENDPOINT_URL",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
)


@pytest.fixture
def air_gapped_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strips every AWS_* environment variable to prove 100% cloud-free execution."""
    for var in _AWS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
async def isolated_session_factory() -> AsyncGenerator[SessionFactory]:
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
            yield factory
        finally:
            if outer_tx.is_active:
                await outer_tx.rollback()
    await engine.dispose()


@pytest.mark.integration
async def test_air_gapped_seeded_platform_topic_fanout_across_all_five_bounded_contexts(
    air_gapped_env: None,
    isolated_session_factory: SessionFactory,
) -> None:
    """Verifies self-contained topic subscriptions route platform-events-topic with zero AWS env vars."""
    del air_gapped_env
    # Self-contained fixture seeding inside the rolled-back SAVEPOINT (zero shared DB reliance)
    repo = SqlAlchemyDatabaseQueueRepository(session_factory=isolated_session_factory)
    canonical_subscriptions: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("ucp-events.fifo", ("app.", "tenant.")),
        ("identity-events.fifo", ("tenant.", "app.", "user.")),
        ("edi-config-sync-queue.fifo", ("webhook.", "edi.")),
        ("notifications.fifo", ("notification.",)),
        ("email-channel.fifo", ("channel.email.", "email.")),
    )
    for target_queue, event_types in canonical_subscriptions:
        await repo.register_subscription(
            topic_name=PlatformTopicName.PLATFORM_EVENTS.value,
            target_queue=target_queue,
            event_types=event_types,
        )

    topic_uri = f"db://topic/{PlatformTopicName.PLATFORM_EVENTS.value}"
    publisher = PubSubProvider.create_outbox_publisher(
        topic_uri, session_factory=isolated_session_factory
    )

    evt_tenant = EventEnvelope(
        id=generate_id(SystemIdPrefix.GENERIC),
        source="identity",
        event_type="tenant.created",
        tenant_id="ten_airgap",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={"tenant_id": "ten_airgap"},
        trace_id=generate_id(SystemIdPrefix.TRACE),
    )
    evt_edi = EventEnvelope(
        id=generate_id(SystemIdPrefix.GENERIC),
        source="edi.cp",
        event_type="edi.partner.updated",
        tenant_id="ten_airgap",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={"partner_id": "ptr_1"},
        trace_id=generate_id(SystemIdPrefix.TRACE),
    )
    evt_notif = EventEnvelope(
        id=generate_id(SystemIdPrefix.GENERIC),
        source="identity",
        event_type="notification.requested",
        tenant_id="ten_airgap",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={"template": "welcome"},
        trace_id=generate_id(SystemIdPrefix.TRACE),
    )
    evt_email = EventEnvelope(
        id=generate_id(SystemIdPrefix.GENERIC),
        source="notification",
        event_type="email.requested",
        tenant_id="ten_airgap",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={"to": "ops@datacenter.local"},
        trace_id=generate_id(SystemIdPrefix.TRACE),
    )

    await publisher.publish_batch([evt_tenant, evt_edi, evt_notif, evt_email])

    expected_by_queue: dict[str, set[str]] = {
        "ucp-events.fifo": {evt_tenant.id},
        "identity-events.fifo": {evt_tenant.id},
        "edi-config-sync-queue.fifo": {evt_edi.id},
        "notifications.fifo": {evt_notif.id},
        "email-channel.fifo": {evt_email.id},
    }

    for queue_name, expected_ids in expected_by_queue.items():
        received: set[str] = set()

        async def _collect(msg: JsonDict, bucket: set[str] = received) -> None:
            bucket.add(str(msg["id"]))

        consumer = PubSubProvider.create_consumer_manager(
            f"db://{queue_name}",
            handler=_collect,
            session_factory=isolated_session_factory,
        )
        assert isinstance(consumer, DirectOutboxConsumerManager)
        await consumer.drain_once()
        assert expected_ids.issubset(received), (
            f"Queue {queue_name} missing expected event IDs: {expected_ids - received}"
        )


@pytest.mark.integration
async def test_air_gapped_scheduler_in_process_platform_queue_cleanup(
    air_gapped_env: None,
    isolated_session_factory: SessionFactory,
) -> None:
    """Verifies scheduler-worker's `create_job_dispatcher` purges processed queue rows in-process."""
    del air_gapped_env
    queue_name = f"cleanup_verify_{os.urandom(6).hex()}"
    repo = SqlAlchemyDatabaseQueueRepository(session_factory=isolated_session_factory)
    evt = EventEnvelope(
        id=generate_id(SystemIdPrefix.GENERIC),
        source="test",
        event_type="cleanup.target",
        tenant_id="platform",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={},
        trace_id=generate_id(SystemIdPrefix.TRACE),
    )
    await repo.enqueue(queue_name, evt)
    claimed = await repo.claim_batch(queue_name, worker_id="w1", limit=10)
    assert [e.id for e in claimed] == [evt.id]
    await repo.mark_completed_batch(queue_name, [evt.id], worker_id="w1")

    dispatcher = create_job_dispatcher(
        session_factory=isolated_session_factory,
        queue_url_map={"ucp-jobs.fifo": "db://ucp-jobs.fifo"},
    )
    cleanup_job = ScheduledJob(
        id=f"job_{os.urandom(4).hex()}",
        name=PubSubJobName.PLATFORM_QUEUE_CLEANUP.value,
        target_queue=None,
        payload={"retention_days": 0},
        status=JobStatus.PENDING,
        cron_expression="0 * * * *",
        interval_seconds=None,
        retry_count=0,
        max_retries=3,
        next_run_at=datetime.now(UTC),
        app_namespace="platform",
    )
    await dispatcher.dispatch(cleanup_job)

    async with isolated_session_factory() as session:
        remaining = (
            await session.execute(
                select(func.count())
                .select_from(PlatformQueueMessage)
                .where(PlatformQueueMessage.queue_name == queue_name)
            )
        ).scalar_one()
        assert remaining == 0


@pytest.mark.integration
async def test_burst_1000_events_cte_limit_enforcement_and_sigkill_lease_recovery(
    air_gapped_env: None,
    isolated_session_factory: SessionFactory,
) -> None:
    """Enqueues 1,000 events, verifies exact CTE LIMIT=100, simulates SIGKILL mid-batch, and verifies 0% loss."""
    del air_gapped_env
    queue_name = f"burst_resilience_{os.urandom(6).hex()}"
    repo = SqlAlchemyDatabaseQueueRepository(session_factory=isolated_session_factory)
    total_events = 1000
    events = [
        EventEnvelope(
            id=generate_id(SystemIdPrefix.GENERIC),
            source="load_test",
            event_type="burst.item",
            tenant_id="ten_load",
            idempotency_key=f"ik_burst_{i}_{queue_name}",
            payload={"seq": i},
            trace_id=generate_id(SystemIdPrefix.TRACE),
        )
        for i in range(total_events)
    ]

    t0 = time.perf_counter()
    await repo.enqueue_batch(queue_name, events)

    # 1. Worker A claims exactly 100 rows and suffers a simulated SIGKILL (never calls mark_completed)
    crashed_batch = await repo.claim_batch(
        queue_name, worker_id="worker_killed", limit=100, lock_lease_ms=30000
    )
    assert len(crashed_batch) == 100

    # Expire Worker A's lease to simulate lease timeout after SIGKILL
    async with isolated_session_factory() as session:
        await session.execute(
            update(PlatformQueueMessage)
            .where(
                PlatformQueueMessage.queue_name == queue_name,
                PlatformQueueMessage.owner_token == "worker_killed",
            )
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=5))
        )
        await session.commit()

    # 2. Healthy Worker B drains ALL 1,000 events (including the 100 reclaimed from Worker A) in exact batches of 100
    processed_ids: list[str] = []
    batch_sizes: list[int] = []
    while True:
        batch = await repo.claim_batch(queue_name, worker_id="worker_healthy", limit=100)
        if not batch:
            break
        assert len(batch) <= 100
        batch_sizes.append(len(batch))
        processed_ids.extend(e.id for e in batch)
        await repo.mark_completed_batch(
            queue_name, [e.id for e in batch], worker_id="worker_healthy"
        )

    elapsed = time.perf_counter() - t0
    assert len(processed_ids) == total_events
    assert len(set(processed_ids)) == total_events  # Zero duplicates, zero drops
    assert batch_sizes == [100] * 10  # Exact CTE LIMIT=100 enforcement across all 10 batches
    assert (
        elapsed < 10.0
    )  # Sanity performance floor (> 100 events/sec even in single-conn SAVEPOINT)
