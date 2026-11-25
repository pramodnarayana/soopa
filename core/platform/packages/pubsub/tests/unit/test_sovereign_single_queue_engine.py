"""Unit tests for the Single-Queue PostgreSQL Engine (`db://`) and AMQP adapters."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest
from outbox.application.outbox_sweeper_use_case import LeaseOnlyOutboxSweeperUseCase
from outbox.testing.fakes import FakeOutboxRepository, FakeShardOutboxDrainRepository
from pubsub.adapters.amqp.amqp_consumer_manager import AmqpConsumerManager, AmqpOutboxPublisher
from pubsub.adapters.database.database_outbox_publisher import (
    DatabaseOutboxPublisher,
    DatabasePublisherAdapter,
)
from pubsub.adapters.database.direct_handler_outbox_publisher import DirectHandlerOutboxPublisher
from pubsub.adapters.database.direct_outbox_consumer_manager import DirectOutboxConsumerManager
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from pubsub.domain.dtos import AckableMessage, TopicSubscriptionSpec
from pubsub.domain.enums import (
    ConsumerVerdict,
    PayloadDispatchMode,
    is_database_queue_uri,
    is_database_topic_uri,
    normalize_database_queue_name,
    normalize_database_topic_name,
)
from pubsub.enums import ConsumerAction, ConsumerDecision
from pubsub.exceptions import ConsumerTerminalError
from pubsub.ports.database_queue_port import DatabaseQueuePort
from pubsub.provider import PubSubProvider
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope, EventProcessingLane


class FakeDatabaseQueueRepository(DatabaseQueuePort):
    """Test-only in-memory implementation of DatabaseQueuePort (zero global state)."""

    def __init__(self) -> None:
        self.queues: dict[str, list[EventEnvelope]] = {}
        self.completed: dict[str, list[str]] = {}
        self.failed: dict[str, list[tuple[str, str, int | None]]] = {}
        self.dead_lettered: dict[str, list[tuple[str, str]]] = {}
        self.subscriptions: dict[str, dict[str, tuple[str, ...] | None]] = {}

    async def enqueue(self, queue_name: str, event: EventEnvelope) -> None:
        self.queues.setdefault(queue_name, []).append(event)

    async def enqueue_batch(self, queue_name: str, events: Sequence[EventEnvelope]) -> list[str]:
        self.queues.setdefault(queue_name, []).extend(events)
        return [e.id for e in events]

    async def register_subscription(
        self,
        topic_name: str,
        target_queue: str,
        *,
        event_types: Sequence[str] | None = None,
    ) -> None:
        self.subscriptions.setdefault(topic_name, {})[target_queue] = (
            tuple(event_types) if event_types else None
        )

    async def publish_to_topic(self, topic_name: str, event: EventEnvelope) -> list[str]:
        return await self.publish_batch_to_topic(topic_name, [event])

    async def publish_batch_to_topic(
        self, topic_name: str, events: Sequence[EventEnvelope]
    ) -> list[str]:
        subs = self.subscriptions.get(topic_name, {})
        for target_queue, filters in subs.items():
            for evt in events:
                if not filters or any(
                    (evt.event_type.startswith(p[:-1]) if p.endswith("*") else False)
                    or (evt.event_type.startswith(p) if p.endswith(".") else False)
                    or evt.event_type == p
                    for p in filters
                ):
                    self.queues.setdefault(target_queue, []).append(evt)
        return [e.id for e in events]

    async def claim_batch(
        self,
        queue_name: str,
        worker_id: str,
        limit: int = 500,
        lock_lease_ms: int = 30000,
    ) -> list[EventEnvelope]:
        bucket = self.queues.get(queue_name, [])
        claimed = bucket[:limit]
        self.queues[queue_name] = bucket[limit:]
        return claimed

    async def mark_completed_batch(
        self, queue_name: str, event_ids: Sequence[str], worker_id: str
    ) -> None:
        self.completed.setdefault(queue_name, []).extend(event_ids)

    async def mark_failed_batch(
        self,
        queue_name: str,
        event_ids: Sequence[str],
        worker_id: str,
        error_message: str,
        *,
        retry_delay_seconds: int | None = None,
    ) -> None:
        for eid in event_ids:
            self.failed.setdefault(queue_name, []).append((eid, error_message, retry_delay_seconds))

    async def mark_dead_letter_batch(
        self,
        queue_name: str,
        event_ids: Sequence[str],
        worker_id: str,
        error_message: str,
    ) -> None:
        for eid in event_ids:
            self.dead_lettered.setdefault(queue_name, []).append((eid, error_message))

    async def cleanup_processed(self, retention_days: int = 7) -> int:
        return 0


def _make_event(event_id: str, event_type: str = "test.event") -> EventEnvelope:
    return EventEnvelope(
        id=event_id,
        source="test_suite",
        event_type=event_type,
        tenant_id="ten_001",
        idempotency_key=f"idem_{event_id}",
        payload={"record_id": event_id},
        trace_id=f"tr_{event_id}",
        lane=EventProcessingLane.REALTIME,
    )


def test_database_queue_uri_helpers() -> None:
    assert is_database_queue_uri("db://ip-orchestrator-realtime")
    assert is_database_queue_uri("outbox://edi-compute")
    assert is_database_queue_uri("postgres://notification-jobs.fifo")
    assert not is_database_queue_uri("sqs://my-queue")
    assert not is_database_queue_uri("")
    assert not is_database_queue_uri(None)
    assert normalize_database_queue_name("db://edi-compute/") == "edi-compute"


@pytest.mark.asyncio
async def test_direct_handler_outbox_publisher_ack_and_nack_dispositions() -> None:
    received: list[str] = []

    async def handler(payload: JsonDict) -> ConsumerAction:
        evt_id = str(payload.get("id"))
        received.append(evt_id)
        if evt_id == "evt_nack":
            return ConsumerAction.NACK
        if evt_id == "evt_terminal":
            raise ConsumerTerminalError("Malformed payload")
        if evt_id == "evt_crash":
            raise RuntimeError("Transient DB timeout")
        return ConsumerAction.ACK

    publisher = DirectHandlerOutboxPublisher(handler=handler, queue_name="test-direct")
    events = [
        _make_event("evt_ok"),
        _make_event("evt_nack"),
        _make_event("evt_terminal"),
        _make_event("evt_crash"),
    ]
    successful_ids = await publisher.publish_batch(events)
    assert successful_ids == ["evt_ok"]
    assert received == ["evt_ok", "evt_nack", "evt_terminal", "evt_crash"]

    structured = await publisher.publish_batch_structured(events)
    assert [(o.event_id, o.disposition.value) for o in structured] == [
        ("evt_ok", "ACK"),
        ("evt_nack", "NACK"),
        ("evt_terminal", "DLQ"),
        ("evt_crash", "NACK"),
    ]


@pytest.mark.asyncio
async def test_direct_handler_outbox_publisher_ackable_message_mode() -> None:
    processed_ids: list[str] = []

    async def ackable_handler(ackable_msg: AckableMessage) -> ConsumerVerdict:
        assert isinstance(ackable_msg.payload, bytes)
        body = json.loads(ackable_msg.payload.decode("utf-8"))
        msg_id = str(body["id"])
        processed_ids.append(msg_id)
        if msg_id == "evt_reject":
            await ackable_msg.nack(requeue=False)
            return ConsumerVerdict.REJECT
        return ConsumerVerdict.ACK

    publisher = DirectHandlerOutboxPublisher(
        handler=ackable_handler,
        queue_name="ackable-q",
        dispatch_mode=PayloadDispatchMode.ACKABLE_MESSAGE,
    )
    outcomes = await publisher.dispatch_batch_outcomes(
        [_make_event("evt_1"), _make_event("evt_reject")]
    )
    assert [(o.event_id, o.action) for o in outcomes] == [
        ("evt_1", ConsumerAction.ACK),
        ("evt_reject", ConsumerAction.DLQ),
    ]
    assert processed_ids == ["evt_1", "evt_reject"]


@pytest.mark.asyncio
async def test_direct_outbox_consumer_manager_preserves_dlq_and_visibility_timeout() -> None:
    fake_queue = FakeDatabaseQueueRepository()
    await fake_queue.enqueue_batch(
        "rate-limited-q",
        [_make_event("e_ack"), _make_event("e_rate_limit"), _make_event("e_dlq")],
    )

    async def handler(payload: JsonDict) -> ConsumerDecision:
        eid = str(payload["id"])
        if eid == "e_rate_limit":
            return ConsumerDecision(action=ConsumerAction.NACK, visibility_timeout_seconds=120)
        if eid == "e_dlq":
            return ConsumerDecision(action=ConsumerAction.DLQ)
        return ConsumerDecision(action=ConsumerAction.ACK)

    consumer = PubSubProvider.create_consumer_manager(
        "db://rate-limited-q",
        handler=handler,
        database_queue=fake_queue,
    )
    assert isinstance(consumer, DirectOutboxConsumerManager)
    await consumer.drain_once()

    assert fake_queue.completed["rate-limited-q"] == ["e_ack"]
    assert fake_queue.failed["rate-limited-q"] == [
        ("e_rate_limit", "Handler returned NACK", 120),
    ]
    assert fake_queue.dead_lettered["rate-limited-q"] == [
        ("e_dlq", "Handler returned DLQ"),
    ]


@pytest.mark.asyncio
async def test_direct_outbox_consumer_manager_drains_sharded_repository() -> None:
    e1 = _make_event("e_shard_1", "ip.inbound_record.created")
    e2 = _make_event("e_shard_2", "ip.inbound_record.created")
    shard_repo = FakeShardOutboxDrainRepository({"shard_1": [e1, e2]})

    handled: list[str] = []

    async def handler(event: JsonDict) -> ConsumerDecision:
        handled.append(str(event["id"]))
        return ConsumerDecision(action=ConsumerAction.ACK)

    manager = PubSubProvider.create_consumer_manager(
        source_uri="db://ip-orchestrator-realtime",
        handler=handler,
        shard_drain_repo=shard_repo,
        batch_size=10,
    )
    assert isinstance(manager, DirectOutboxConsumerManager)

    drained_count = await manager.drain_once()
    assert drained_count == 2
    assert handled == ["e_shard_1", "e_shard_2"]
    assert shard_repo.completed_batches[0][1] == ("e_shard_1", "e_shard_2")


@pytest.mark.asyncio
async def test_direct_outbox_consumer_manager_drains_global_repository() -> None:
    global_repo = FakeOutboxRepository()
    e1 = _make_event("e_glob_1", "notification.requested")
    global_repo.events.append(e1)

    handled: list[str] = []

    async def handler(payload: JsonDict) -> None:
        handled.append(str(payload["id"]))

    manager = PubSubProvider.create_consumer_manager(
        source_uri="db://notification-queue",
        handler=handler,
        global_outbox_repo=global_repo,
        batch_size=10,
    )
    assert isinstance(manager, DirectOutboxConsumerManager)

    await manager.drain_once()
    assert handled == ["e_glob_1"]
    assert any(evt_id == "e_glob_1" for evt_id, _ in global_repo.completed_events)


@pytest.mark.asyncio
async def test_database_queue_port_publisher_and_consumer_roundtrip_with_job_dispatcher() -> None:
    fake_db_queue = FakeDatabaseQueueRepository()
    outbox_pub = PubSubProvider.create_outbox_publisher(
        "db://notification-jobs.fifo", database_queue=fake_db_queue
    )
    msg_pub = PubSubProvider.create_publisher(
        "db://notification-jobs.fifo", database_queue=fake_db_queue
    )
    assert isinstance(outbox_pub, DatabaseOutboxPublisher)
    assert isinstance(msg_pub, DatabasePublisherAdapter)

    job_event = EventEnvelope(
        id="evt_job_1",
        source="platform.scheduler",
        event_type="job.outbox_cleanup.scheduled",
        tenant_id="platform",
        idempotency_key="idem_job_1",
        payload={"job_id": "j1", "job_name": "outbox_cleanup", "payload": {}},
    )
    await outbox_pub.publish(job_event)
    raw_job = json.dumps({"job_id": "j2", "job_name": "outbox_cleanup", "payload": {}}).encode()
    res = await msg_pub.publish("db://notification-jobs.fifo", raw_job)
    assert res.is_ok

    executed: list[str] = []
    dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME.value)

    async def _on_cleanup(msg: JsonDict) -> None:
        executed.append(str(msg.get("id", "unknown")))

    dispatcher.subscribe("outbox_cleanup", _on_cleanup)

    consumer = PubSubProvider.create_consumer_manager(
        "db://notification-jobs.fifo",
        handler=dispatcher.dispatch,
        database_queue=fake_db_queue,
    )
    assert isinstance(consumer, DirectOutboxConsumerManager)
    count = await consumer.drain_once()
    assert count == 2
    assert len(executed) == 2
    assert len(fake_db_queue.completed["notification-jobs.fifo"]) == 2


@pytest.mark.asyncio
async def test_amqp_adapters_fail_loudly_without_real_broker_driver() -> None:
    outbox_pub = PubSubProvider.create_outbox_publisher("amqp://edi.deliver.queue")
    assert isinstance(outbox_pub, AmqpOutboxPublisher)
    with pytest.raises(NotImplementedError, match="AMQP broker driver"):
        await outbox_pub.publish(_make_event("e_amqp_1"))

    async def noop_handler(payload: JsonDict) -> None:
        pass

    consumer = PubSubProvider.create_consumer_manager(
        "amqp://edi.deliver.queue", handler=noop_handler
    )
    assert isinstance(consumer, AmqpConsumerManager)
    with pytest.raises(NotImplementedError, match="AMQP broker driver"):
        consumer.start()


@pytest.mark.asyncio
async def test_database_topic_uri_helpers_and_consumer_self_subscription() -> None:
    assert is_database_topic_uri("db://topic/platform-events-topic") is True
    assert is_database_topic_uri("outbox://topic/ip-events-topic") is True
    assert is_database_topic_uri("db://ip-orchestrator-realtime") is False
    assert is_database_topic_uri("arn:aws:sns:us-east-1:000:platform-events") is False
    assert normalize_database_topic_name("db://topic/platform-events-topic") == (
        "platform-events-topic"
    )

    fake_queue = FakeDatabaseQueueRepository()
    identity_msgs: list[JsonDict] = []
    ucp_msgs: list[JsonDict] = []

    async def on_identity(msg: JsonDict) -> None:
        identity_msgs.append(msg)

    async def on_ucp(msg: JsonDict) -> None:
        ucp_msgs.append(msg)

    identity_consumer = PubSubProvider.create_consumer_manager(
        "db://identity-events",
        handler=on_identity,
        database_queue=fake_queue,
        subscribe_topics=(
            TopicSubscriptionSpec(
                topic_name="db://topic/platform-events-topic",
                event_types=("tenant.", "user."),
            ),
        ),
    )
    ucp_consumer = PubSubProvider.create_consumer_manager(
        "db://ucp-events",
        handler=on_ucp,
        database_queue=fake_queue,
        subscribe_topics=(
            TopicSubscriptionSpec(
                topic_name="platform-events-topic",
                event_types=("tenant.", "app."),
            ),
        ),
    )
    assert isinstance(identity_consumer, DirectOutboxConsumerManager)
    assert isinstance(ucp_consumer, DirectOutboxConsumerManager)

    await identity_consumer.ensure_subscriptions()
    await ucp_consumer.ensure_subscriptions()

    topic_pub = PubSubProvider.create_outbox_publisher(
        "db://topic/platform-events-topic",
        database_queue=fake_queue,
    )
    assert isinstance(topic_pub, DatabaseOutboxPublisher)
    assert topic_pub.is_topic is True

    await topic_pub.publish_batch(
        [
            _make_event("evt_tenant", event_type="tenant.deleted"),
            _make_event("evt_user", event_type="user.created"),
        ]
    )

    assert await identity_consumer.drain_once() == 2
    assert await ucp_consumer.drain_once() == 1
    assert [m["id"] for m in identity_msgs] == ["evt_tenant", "evt_user"]
    assert [m["id"] for m in ucp_msgs] == ["evt_tenant"]


@pytest.mark.asyncio
async def test_shard_outbox_drain_routes_dlq_to_dead_letter_and_forwards_to_dlq_publisher() -> None:
    """Verifies DLQ outcomes never mark shard rows PROCESSED and forward to dlq_publisher."""
    e_ok = _make_event("e_ok", "edi.execute_delivery")
    e_dlq = _make_event("e_dlq", "edi.execute_delivery")
    e_nack = _make_event("e_nack", "edi.execute_delivery")
    shard_repo = FakeShardOutboxDrainRepository({"shard_1": [e_ok, e_dlq, e_nack]})
    fake_dlq_queue = FakeDatabaseQueueRepository()
    dlq_publisher = PubSubProvider.create_outbox_publisher(
        "db://edi-deliver-dlq",
        database_queue=fake_dlq_queue,
    )

    async def handler(event: JsonDict) -> ConsumerDecision:
        eid = str(event["id"])
        if eid == "e_ok":
            return ConsumerDecision(action=ConsumerAction.ACK)
        if eid == "e_dlq":
            return ConsumerDecision(action=ConsumerAction.DLQ)
        return ConsumerDecision(action=ConsumerAction.NACK, visibility_timeout_seconds=45)

    manager = PubSubProvider.create_consumer_manager(
        source_uri="db://edi-deliver",
        handler=handler,
        shard_drain_repo=shard_repo,
        dlq_publisher=dlq_publisher,
        batch_size=10,
    )
    assert isinstance(manager, DirectOutboxConsumerManager)

    drained = await manager.drain_once()
    assert drained == 1
    assert shard_repo.completed_batches[0][1] == ("e_ok",)
    assert shard_repo.dead_letter_batches[0][1] == ("e_dlq",)
    assert shard_repo.failed_batches[0][1] == ("e_nack",)
    assert [e.id for e in fake_dlq_queue.queues["edi-deliver-dlq"]] == ["e_dlq"]


@pytest.mark.asyncio
async def test_lease_only_outbox_sweeper_recovers_leases_polymorphically() -> None:
    repo = FakeOutboxRepository()
    sweeper = LeaseOnlyOutboxSweeperUseCase(repository=repo, lock_lease_ms=15000)
    await sweeper.execute()
    assert repo.stuck_events_swept == 5
