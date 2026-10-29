"""Unit tests for EventEnvelopeDispatcher and concurrent AwsBatchPublisherBase (Zero Mocks)."""

from __future__ import annotations

import asyncio
import json

import pytest
from pubsub.aws.aws_sqs_publisher import AwsSqsPublisher
from pubsub.enums import ConsumerAction
from pubsub.envelope_dispatcher import (
    EventEnvelopeDispatcher,
    parse_event_envelope,
)
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope, EventProcessingLane


@pytest.mark.asyncio
async def test_parse_event_envelope_valid_and_sns_unwrapping() -> None:
    raw: JsonDict = {
        "id": "evt_100",
        "source": "ip.data_plane",
        "event_type": "ip.replica_record.changed",
        "tenant_id": "t_energy",
        "idempotency_key": "ik_100",
        "payload": {"record_ids": ["rep_1", "rep_2"], "stream": "meters"},
        "trace_id": "trc_100",
        "correlation_id": "MTR-100",
        "lane": "bulk",
    }
    res = parse_event_envelope(raw)
    assert res.is_ok
    env = res.unwrap()
    assert env.id == "evt_100"
    assert env.source == "ip.data_plane"
    assert env.event_type == "ip.replica_record.changed"
    assert env.tenant_id == "t_energy"
    assert env.idempotency_key == "ik_100"
    assert env.trace_id == "trc_100"
    assert env.correlation_id == "MTR-100"
    assert env.lane == EventProcessingLane.BULK
    assert env.payload == {"record_ids": ["rep_1", "rep_2"], "stream": "meters"}

    # SNS Notification wrapper should also unwrap cleanly
    sns_wrapped: JsonDict = {
        "Type": "Notification",
        "MessageId": "sns_msg_1",
        "Message": json.dumps(raw),
    }
    sns_res = parse_event_envelope(sns_wrapped)
    assert sns_res.is_ok
    assert sns_res.unwrap() == env


@pytest.mark.asyncio
async def test_event_envelope_dispatcher_routes_and_handles_known_errors_without_exceptions() -> (
    None
):
    dispatcher = EventEnvelopeDispatcher()
    received: list[EventEnvelope] = []

    async def handle_replica_changed(envelope: EventEnvelope) -> ConsumerAction:
        received.append(envelope)
        return ConsumerAction.ACK

    async def handle_retryable(envelope: EventEnvelope) -> ConsumerAction:
        received.append(envelope)
        return ConsumerAction.NACK

    dispatcher.subscribe("ip.replica_record.changed", handle_replica_changed)
    dispatcher.subscribe("ip.outbound_record.created", handle_retryable)

    action_ok = await dispatcher.handle(
        {
            "id": "evt_1",
            "source": "ip.data_plane",
            "event_type": "ip.replica_record.changed",
            "tenant_id": "t_1",
            "idempotency_key": "ik_1",
            "payload": {"record_ids": ["rep_1"]},
            "trace_id": "trc_1",
            "lane": "realtime",
        }
    )
    assert action_ok == ConsumerAction.ACK
    assert len(received) == 1
    assert received[0].lane == EventProcessingLane.REALTIME

    action_nack = await dispatcher.handle(
        {
            "id": "evt_2",
            "source": "ip.data_plane",
            "event_type": "ip.outbound_record.created",
            "tenant_id": "t_1",
            "idempotency_key": "ik_2",
            "payload": {"record_ids": ["out_1"]},
        }
    )
    assert action_nack == ConsumerAction.NACK
    assert len(received) == 2

    # Unregistered event type returns ACK without raising an exception
    action_unknown = await dispatcher.handle(
        {
            "id": "evt_3",
            "source": "ip.data_plane",
            "event_type": "ip.unknown.event",
            "tenant_id": "t_1",
            "idempotency_key": "ik_3",
            "payload": {},
        }
    )
    assert action_unknown == ConsumerAction.ACK

    # Malformed payload (missing event_type or non-dict payload) returns ACK without raising
    action_malformed = await dispatcher.handle({"id": "", "payload": "not_a_dict"})
    assert action_malformed == ConsumerAction.ACK

    # Malformed SNS JSON returns ACK without raising
    action_bad_sns = await dispatcher.handle({"Type": "Notification", "Message": "{bad_json"})
    assert action_bad_sns == ConsumerAction.ACK


class _FakeSqsClient:
    """In-memory fake SQS client tracking concurrent send_message_batch calls."""

    def __init__(self) -> None:
        self.batch_calls: list[list[dict[str, object]]] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def send_message_batch(
        self,
        *,
        QueueUrl: str,
        Entries: list[dict[str, object]],
    ) -> dict[str, object]:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        self.batch_calls.append(Entries)
        return {
            "Successful": [{"Id": str(entry["Id"])} for entry in Entries],
            "Failed": [],
        }


@pytest.mark.asyncio
async def test_aws_batch_publisher_concurrent_10_message_chunks_and_attributes() -> None:
    publisher = AwsSqsPublisher(
        queue_url="https://sqs.us-east-1.amazonaws.com/123456789012/ip-orchestrator-bulk-queue",
        max_concurrent_batches=5,
    )
    fake_client = _FakeSqsClient()
    publisher._client = fake_client

    events = [
        EventEnvelope(
            id=f"evt_{i}",
            source="ip.data_plane",
            event_type="ip.replica_record.changed",
            tenant_id="t_1",
            idempotency_key=f"ik_{i}",
            payload={"record_ids": [f"rep_{i}"]},
            trace_id=f"trc_{i}",
            correlation_id="MTR-100",
            lane=EventProcessingLane.BULK,
        )
        for i in range(35)
    ]

    successful_ids = await publisher.publish_batch(events)
    assert len(successful_ids) == 35
    assert set(successful_ids) == {f"evt_{i}" for i in range(35)}
    assert len(fake_client.batch_calls) == 4  # 10 + 10 + 10 + 5
    # Verify concurrent execution occurred across the 4 chunks
    assert fake_client.max_in_flight > 1

    # Verify MessageAttributes include event_type, lane, and trace_id
    first_entry = fake_client.batch_calls[0][0]
    attrs = first_entry["MessageAttributes"]
    assert isinstance(attrs, dict)
    assert attrs["event_type"]["StringValue"] == "ip.replica_record.changed"
    assert attrs["lane"]["StringValue"] == "bulk"
    assert attrs["trace_id"]["StringValue"] == "trc_0"
