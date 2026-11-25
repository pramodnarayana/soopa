"""Narrow integration tests for SqlAlchemyDatabaseQueueRepository and filtered Outbox draining against real PostgreSQL."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest
from database.models.notifications import NotificationOutbox
from database.models.pubsub import PlatformQueueMessage, PlatformTopicSubscription
from database.provider import get_async_engine
from database.testing import assert_test_database_url
from outbox.adapters.outbound.sqlalchemy_global_outbox_repository import (
    SqlAlchemyGlobalOutboxRepository,
)
from outbox.domain.constants import OutboxStatus
from pubsub.adapters.database.direct_outbox_consumer_manager import DirectOutboxConsumerManager
from pubsub.adapters.database.sqlalchemy_database_queue_repository import (
    SqlAlchemyDatabaseQueueRepository,
)
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from pubsub.domain.dtos import TopicSubscriptionSpec
from pubsub.enums import ConsumerAction, ConsumerDecision
from pubsub.provider import PubSubProvider
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope, EventProcessingLane
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@pytest.fixture
async def isolated_session_factory() -> AsyncGenerator[SessionFactory, None]:
    db_url = assert_test_database_url(os.environ["DATABASE_URL"])
    engine = get_async_engine(db_url, statement_cache_size=0)
    async with engine.connect() as conn:
        outer_tx = await conn.begin()
        try:
            # Ensure pubsub schema & tables exist inside the rolled-back transaction
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
async def test_database_queue_repository_lifecycle_skip_locked_lease_and_backoff(
    isolated_session_factory: SessionFactory,
) -> None:
    repo = SqlAlchemyDatabaseQueueRepository(
        session_factory=isolated_session_factory,
        max_attempts=2,
        base_retry_backoff_seconds=0,
    )
    queue_name = f"test_q_{os.urandom(6).hex()}"

    bulk_evt = EventEnvelope(
        id=generate_id(SystemIdPrefix.GENERIC),
        source="ip.control_plane",
        event_type="ip.sync_run.requested",
        tenant_id="ten_1",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={"sync_run_id": "sr_bulk"},
        trace_id=generate_id(SystemIdPrefix.TRACE),
        lane=EventProcessingLane.BULK,
    )
    rt_evt = EventEnvelope(
        id=generate_id(SystemIdPrefix.GENERIC),
        source="ip.control_plane",
        event_type="ip.sync_run.requested",
        tenant_id="ten_1",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={"sync_run_id": "sr_rt"},
        trace_id=generate_id(SystemIdPrefix.TRACE),
        lane=EventProcessingLane.REALTIME,
    )

    # 1. Enqueue & idempotency deduplication
    await repo.enqueue_batch(queue_name, [bulk_evt, rt_evt])
    await repo.enqueue(queue_name, rt_evt)  # Duplicate idempotency_key ignored

    # 2. Priority lane ordering: REALTIME claimed ahead of BULK
    claimed = await repo.claim_batch(queue_name, worker_id="worker_a", limit=1, lock_lease_ms=30000)
    assert len(claimed) == 1
    assert claimed[0].id == rt_evt.id

    # 3. Concurrent worker skips already-PROCESSING row and claims BULK
    claimed_b = await repo.claim_batch(
        queue_name, worker_id="worker_b", limit=10, lock_lease_ms=30000
    )
    assert [e.id for e in claimed_b] == [bulk_evt.id]

    # 4. Complete rt_evt
    await repo.mark_completed_batch(queue_name, [rt_evt.id], worker_id="worker_a")

    # 5. Simulate stale lease expiration on bulk_evt (worker_b hung)
    async with isolated_session_factory() as session:
        await session.execute(
            update(PlatformQueueMessage)
            .where(PlatformQueueMessage.id == bulk_evt.id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=10))
        )
        await session.commit()

    # Worker C reclaims the lease-expired message
    reclaimed = await repo.claim_batch(
        queue_name, worker_id="worker_c", limit=10, lock_lease_ms=30000
    )
    assert [e.id for e in reclaimed] == [bulk_evt.id]

    # 6. Fail twice -> transitions to FAILED (max_attempts=2)
    await repo.mark_failed_batch(
        queue_name, [bulk_evt.id], worker_id="worker_c", error_message="err1"
    )
    reclaimed2 = await repo.claim_batch(
        queue_name, worker_id="worker_c", limit=10, lock_lease_ms=30000
    )
    assert [e.id for e in reclaimed2] == [bulk_evt.id]
    await repo.mark_failed_batch(
        queue_name, [bulk_evt.id], worker_id="worker_c", error_message="err2"
    )

    # Should no longer be claimable
    assert await repo.claim_batch(queue_name, worker_id="worker_c", limit=10) == []

    async with isolated_session_factory() as session:
        row = (
            await session.execute(
                select(PlatformQueueMessage).where(PlatformQueueMessage.id == bulk_evt.id)
            )
        ).scalar_one()
        assert row.status == OutboxStatus.FAILED.value
        assert row.attempts == 2
        assert row.error_reason == "err2"

    # 7. Chunked cleanup of PROCESSED rows
    deleted = await repo.cleanup_processed(retention_days=0)
    assert deleted >= 1


@pytest.mark.integration
async def test_filtered_global_outbox_stage_isolation_in_postgres(
    isolated_session_factory: SessionFactory,
) -> None:
    """Verifies stage-filtered `FOR UPDATE SKIP LOCKED` claiming prevents cross-stage stealing."""
    suffix = os.urandom(6).hex()
    orch_event_type = f"stage.orchestrator.{suffix}"
    deliv_event_type = f"stage.delivery.{suffix}"

    async with isolated_session_factory() as session:
        session.add_all(
            [
                NotificationOutbox(
                    id=f"out_orch_{suffix}",
                    tenant_id="ten_iso",
                    idempotency_key=f"ik_orch_{suffix}",
                    event_type=orch_event_type,
                    payload={"step": "orchestrate"},
                    status=OutboxStatus.PENDING.value,
                    lane=EventProcessingLane.REALTIME.value,
                ),
                NotificationOutbox(
                    id=f"out_deliv_{suffix}",
                    tenant_id="ten_iso",
                    idempotency_key=f"ik_deliv_{suffix}",
                    event_type=deliv_event_type,
                    payload={"step": "deliver"},
                    status=OutboxStatus.PENDING.value,
                    lane=EventProcessingLane.BULK.value,
                ),
            ]
        )
        await session.commit()

    orch_repo = SqlAlchemyGlobalOutboxRepository(
        session_factory=isolated_session_factory,
        model_cls=NotificationOutbox,
        source="test.global",
        event_types=(orch_event_type,),
        lanes=(EventProcessingLane.REALTIME.value,),
    )
    deliv_repo = SqlAlchemyGlobalOutboxRepository(
        session_factory=isolated_session_factory,
        model_cls=NotificationOutbox,
        source="test.global",
        event_types=(deliv_event_type,),
        lanes=(EventProcessingLane.BULK.value,),
    )

    orch_handled: list[str] = []
    deliv_handled: list[str] = []

    async def handle_orch(payload: JsonDict) -> None:
        orch_handled.append(str(payload["id"]))

    async def handle_deliv(payload: JsonDict) -> None:
        deliv_handled.append(str(payload["id"]))

    orch_consumer = PubSubProvider.create_consumer_manager(
        "db://orch-stage",
        handler=handle_orch,
        global_outbox_repo=orch_repo,
    )
    deliv_consumer = PubSubProvider.create_consumer_manager(
        "db://deliv-stage",
        handler=handle_deliv,
        global_outbox_repo=deliv_repo,
    )
    assert isinstance(orch_consumer, DirectOutboxConsumerManager)
    assert isinstance(deliv_consumer, DirectOutboxConsumerManager)

    # Orchestrator drains ONLY its own event_type and does NOT touch delivery's row
    await orch_consumer.drain_once()
    assert orch_handled == [f"out_orch_{suffix}"]
    assert deliv_handled == []

    # Delivery drains ONLY its own event_type
    await deliv_consumer.drain_once()
    assert deliv_handled == [f"out_deliv_{suffix}"]


@pytest.mark.integration
async def test_database_queue_end_to_end_with_message_dispatcher(
    isolated_session_factory: SessionFactory,
) -> None:
    queue_name = f"jobs_e2e_{os.urandom(6).hex()}"
    queue_uri = f"db://{queue_name}"

    publisher = PubSubProvider.create_outbox_publisher(
        queue_uri, session_factory=isolated_session_factory
    )
    await publisher.publish(
        EventEnvelope(
            id=generate_id(SystemIdPrefix.GENERIC),
            source="platform.scheduler",
            event_type="job.notification_outbox_cleanup.scheduled",
            tenant_id="platform",
            idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
            payload={"job_id": "j_e2e_1", "job_name": "notification_outbox_cleanup", "payload": {}},
        )
    )

    executed: list[str] = []
    dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

    async def on_job(msg: JsonDict) -> None:
        executed.append(str(msg.get("event_type")))

    dispatcher.subscribe("notification_outbox_cleanup", on_job)

    consumer = PubSubProvider.create_consumer_manager(
        queue_uri,
        handler=dispatcher.dispatch,
        session_factory=isolated_session_factory,
    )
    assert isinstance(consumer, DirectOutboxConsumerManager)
    drained = await consumer.drain_once()
    assert drained == 1
    assert executed == ["job.notification_outbox_cleanup.scheduled"]


@pytest.mark.integration
async def test_database_topic_atomic_fanout_and_prefix_filtering_in_postgres(
    isolated_session_factory: SessionFactory,
) -> None:
    """Verifies decoupled `db://topic/` fan-out preserves original EventEnvelope.id across queues."""
    suffix = os.urandom(6).hex()
    topic_name = f"platform-events-{suffix}"
    topic_uri = f"db://topic/{topic_name}"
    identity_q = f"identity-events-{suffix}"
    ucp_q = f"ucp-events-{suffix}"
    edi_q = f"edi-config-sync-{suffix}"

    identity_received: list[tuple[str, str]] = []
    ucp_received: list[tuple[str, str]] = []
    edi_received: list[tuple[str, str]] = []

    async def on_identity(msg: JsonDict) -> None:
        identity_received.append((str(msg["id"]), str(msg["event_type"])))

    async def on_ucp(msg: JsonDict) -> None:
        ucp_received.append((str(msg["id"]), str(msg["event_type"])))

    async def on_edi(msg: JsonDict) -> None:
        edi_received.append((str(msg["id"]), str(msg["event_type"])))

    identity_consumer = PubSubProvider.create_consumer_manager(
        f"db://{identity_q}",
        handler=on_identity,
        session_factory=isolated_session_factory,
        subscribe_topics=(
            TopicSubscriptionSpec(topic_name=topic_uri, event_types=("tenant.", "app.", "user.")),
        ),
    )
    ucp_consumer = PubSubProvider.create_consumer_manager(
        f"db://{ucp_q}",
        handler=on_ucp,
        session_factory=isolated_session_factory,
        subscribe_topics=(
            TopicSubscriptionSpec(topic_name=topic_name, event_types=("app.", "tenant.")),
        ),
    )
    edi_consumer = PubSubProvider.create_consumer_manager(
        f"db://{edi_q}",
        handler=on_edi,
        session_factory=isolated_session_factory,
        subscribe_topics=(
            TopicSubscriptionSpec(topic_name=topic_name, event_types=("webhook.", "edi.")),
        ),
    )
    assert isinstance(identity_consumer, DirectOutboxConsumerManager)
    assert isinstance(ucp_consumer, DirectOutboxConsumerManager)
    assert isinstance(edi_consumer, DirectOutboxConsumerManager)

    # Consumers self-register their subscriptions idempotently (producer knows nothing about queues)
    await identity_consumer.ensure_subscriptions()
    await ucp_consumer.ensure_subscriptions()
    await edi_consumer.ensure_subscriptions()

    async with isolated_session_factory() as session:
        subs = list(
            (
                await session.execute(
                    select(PlatformTopicSubscription).where(
                        PlatformTopicSubscription.topic_name == topic_name
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(subs) == 3

    tenant_evt = EventEnvelope(
        id=generate_id(SystemIdPrefix.GENERIC),
        source="identity",
        event_type="tenant.deleted",
        tenant_id="ten_1",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={"tenant_id": "ten_1"},
        trace_id=generate_id(SystemIdPrefix.TRACE),
    )
    edi_evt = EventEnvelope(
        id=generate_id(SystemIdPrefix.GENERIC),
        source="edi.cp",
        event_type="edi.partner.updated",
        tenant_id="ten_1",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={"partner_id": "p_1"},
        trace_id=generate_id(SystemIdPrefix.TRACE),
    )

    topic_publisher = PubSubProvider.create_outbox_publisher(
        topic_uri, session_factory=isolated_session_factory
    )
    await topic_publisher.publish_batch([tenant_evt, edi_evt])

    # Also verify direct MessagePublisherPort (`create_publisher`) fans out cleanly to topics
    direct_publisher = PubSubProvider.create_publisher(
        topic_uri, session_factory=isolated_session_factory
    )
    user_evt = EventEnvelope(
        id=generate_id(SystemIdPrefix.GENERIC),
        source="identity",
        event_type="user.created",
        tenant_id="ten_1",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={"user_id": "u_1"},
        trace_id=generate_id(SystemIdPrefix.TRACE),
    )
    pub_res = await direct_publisher.publish(topic_uri, user_evt)
    assert pub_res.is_ok

    assert await identity_consumer.drain_once() == 2
    assert await ucp_consumer.drain_once() == 1
    assert await edi_consumer.drain_once() == 1

    # Exact original EventEnvelope.id preserved across BOTH subscriber queues (composite PK)
    assert identity_received == [
        (tenant_evt.id, "tenant.deleted"),
        (user_evt.id, "user.created"),
    ]
    assert ucp_received == [(tenant_evt.id, "tenant.deleted")]
    assert edi_received == [(edi_evt.id, "edi.partner.updated")]


@pytest.mark.integration
async def test_database_queue_exponential_backoff_visibility_timeout_and_dlq_in_postgres(
    isolated_session_factory: SessionFactory,
) -> None:
    """Verifies capped exponential backoff, explicit visibility_timeout_seconds, and immediate DLQ."""
    queue_name = f"backoff_dlq_{os.urandom(6).hex()}"
    repo = SqlAlchemyDatabaseQueueRepository(
        session_factory=isolated_session_factory,
        max_attempts=5,
        base_retry_backoff_seconds=10,
        max_retry_backoff_seconds=300,
    )
    evt_exp = EventEnvelope(
        id=generate_id(SystemIdPrefix.GENERIC),
        source="ip.delivery",
        event_type="ip.outbound.created",
        tenant_id="ten_1",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={"kind": "exp"},
        trace_id=generate_id(SystemIdPrefix.TRACE),
    )
    evt_custom = EventEnvelope(
        id=generate_id(SystemIdPrefix.GENERIC),
        source="ip.delivery",
        event_type="ip.outbound.created",
        tenant_id="ten_1",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={"kind": "custom_delay"},
        trace_id=generate_id(SystemIdPrefix.TRACE),
    )
    evt_dlq = EventEnvelope(
        id=generate_id(SystemIdPrefix.GENERIC),
        source="ip.delivery",
        event_type="ip.outbound.created",
        tenant_id="ten_1",
        idempotency_key=generate_id(SystemIdPrefix.IDEMPOTENCY),
        payload={"kind": "dlq"},
        trace_id=generate_id(SystemIdPrefix.TRACE),
    )
    await repo.enqueue_batch(queue_name, [evt_exp, evt_custom, evt_dlq])

    async def handler(msg: JsonDict) -> ConsumerDecision:
        eid = str(msg["id"])
        if eid == evt_dlq.id:
            return ConsumerDecision(action=ConsumerAction.DLQ)
        if eid == evt_custom.id:
            return ConsumerDecision(action=ConsumerAction.NACK, visibility_timeout_seconds=120)
        return ConsumerDecision(action=ConsumerAction.NACK)

    consumer = PubSubProvider.create_consumer_manager(
        f"db://{queue_name}",
        handler=handler,
        database_queue=repo,
    )
    assert isinstance(consumer, DirectOutboxConsumerManager)
    before = datetime.now(UTC)
    await consumer.drain_once()

    async with isolated_session_factory() as session:
        rows = {
            r.id: r
            for r in (
                await session.execute(
                    select(PlatformQueueMessage).where(
                        PlatformQueueMessage.queue_name == queue_name
                    )
                )
            )
            .scalars()
            .all()
        }
        # DLQ transitions immediately to FAILED on attempt 1 (without waiting for max_attempts=5)
        assert rows[evt_dlq.id].status == OutboxStatus.FAILED.value
        assert rows[evt_dlq.id].attempts == 1
        assert rows[evt_dlq.id].next_retry_at is None

        # Custom visibility_timeout_seconds=120 sets next_retry_at ~120s in the future
        custom_retry = rows[evt_custom.id].next_retry_at
        assert rows[evt_custom.id].status == OutboxStatus.PENDING.value
        assert custom_retry is not None
        assert 110 <= (custom_retry - before).total_seconds() <= 135

        # Default exponential backoff: attempt 0 -> 10 * 2^0 = 10s
        exp_retry = rows[evt_exp.id].next_retry_at
        assert rows[evt_exp.id].status == OutboxStatus.PENDING.value
        assert exp_retry is not None
        assert 5 <= (exp_retry - before).total_seconds() <= 20

    # Immediate re-claim sees 0 ready messages because both PENDING rows are in backoff window
    assert await repo.claim_batch(queue_name, worker_id="w_check", limit=10) == []
