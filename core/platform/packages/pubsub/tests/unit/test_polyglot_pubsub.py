"""Unit tests for universal multi-broker PubSubProvider, ports, and adapters."""

from __future__ import annotations

import pytest
from pubsub import (
    AckableMessage,
    AmqpPublisherAdapter,
    AwsMessagePublisherAdapter,
    ConsumerVerdict,
    InMemoryConsumerManager,
    InMemoryPublisherAdapter,
    KafkaPublisherAdapter,
    PubSubProvider,
    UnsupportedBrokerSchemeError,
)
from pubsub.adapters.aws.aws_sns_outbox_publisher import AwsSnsOutboxPublisher
from pubsub.adapters.aws.aws_sqs_outbox_publisher import AwsSqsOutboxPublisher


def test_pubsub_provider_scheme_resolution() -> None:
    # 1. Kafka scheme
    kafka_pub = PubSubProvider.create_publisher("kafka://mdm.meter_readings.inbound")
    assert isinstance(kafka_pub, KafkaPublisherAdapter)

    # 2. AMQP scheme
    amqp_pub = PubSubProvider.create_publisher("amqp://orders_exchange/order.created")
    assert isinstance(amqp_pub, AmqpPublisherAdapter)

    # 3. Memory scheme
    mem_pub = PubSubProvider.create_publisher("memory://test.queue")
    assert isinstance(mem_pub, InMemoryPublisherAdapter)

    # 4. SQS scheme
    sqs_pub = PubSubProvider.create_publisher("sqs://my-queue")
    assert isinstance(sqs_pub, AwsMessagePublisherAdapter)

    # 5. Unsupported scheme
    with pytest.raises(UnsupportedBrokerSchemeError):
        PubSubProvider.create_publisher("invalidproto://my-destination")


def test_pubsub_provider_outbox_resolution() -> None:
    sqs = PubSubProvider.create_outbox_publisher(
        "https://sqs.us-east-1.amazonaws.com/123/q", region_name="us-east-1"
    )
    assert isinstance(sqs, AwsSqsOutboxPublisher)

    sns = PubSubProvider.create_outbox_publisher(
        "arn:aws:sns:us-east-1:123:topic", region_name="us-east-1"
    )
    assert isinstance(sns, AwsSnsOutboxPublisher)


@pytest.mark.asyncio
async def test_kafka_publisher_adapter_in_memory_mode() -> None:
    pub = KafkaPublisherAdapter(use_in_memory=True)
    res = await pub.publish(
        destination_uri="kafka://test.readings",
        message=b'{"meter_id": "MTR-1", "val": 42.0}',
        key=b"MTR-1",
        headers={"tenant_id": "bescom"},
    )
    assert res.is_ok
    dto = res.unwrap()
    assert dto.destination_uri == "kafka://test.readings"
    assert dto.offset == 0
    assert len(pub.in_memory_records) == 1
    topic, val, k, h = pub.in_memory_records[0]
    assert topic == "test.readings"
    assert val == b'{"meter_id": "MTR-1", "val": 42.0}'
    assert k == b"MTR-1"
    assert h is not None and h.get("tenant_id") == "bescom"


@pytest.mark.asyncio
async def test_in_memory_publisher_and_consumer_round_trip() -> None:
    received_messages: list[AckableMessage] = []

    async def sample_handler(msg: AckableMessage) -> ConsumerVerdict:
        received_messages.append(msg)
        return ConsumerVerdict.ACK

    consumer_mgr = InMemoryConsumerManager(
        source_uri="memory://test.stream",
        handler=sample_handler,
    )
    consumer_mgr.start()
    assert await consumer_mgr.health_check()

    verdict = await consumer_mgr.deliver_message(
        payload=b"test payload bytes",
        headers={"source": "pytest"},
        message_id="msg_999",
    )
    assert verdict == ConsumerVerdict.ACK
    assert len(received_messages) == 1
    assert received_messages[0].payload == b"test payload bytes"
    assert "msg_999" in consumer_mgr.acked_message_ids

    await consumer_mgr.stop()
    assert not await consumer_mgr.health_check()
