"""Unit tests for streaming subscriber transports verifying strict post-commit ACKs."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from ip.engine.adapters.outbound.transports.amqp_subscribe_transport import (
    AmqpConsumerClientPort,
    AmqpMessageHandlePort,
    AmqpSubscribeTransport,
)
from ip.engine.adapters.outbound.transports.cloud_queue_subscribe_transport import (
    CloudQueueConsumerClientPort,
    CloudQueueMessageHandlePort,
    CloudQueueSubscribeTransport,
)
from ip.engine.adapters.outbound.transports.kafka_subscribe_transport import (
    KafkaConsumerClientPort,
    KafkaSubscribeTransport,
)
from ip.engine.adapters.outbound.transports.mqtt_subscribe_transport import (
    MqttConsumerClientPort,
    MqttMessageHandlePort,
    MqttSubscribeTransport,
)
from ip.engine.domain.enums import AckVerdict
from ip.engine.domain.exceptions import ConnectionCheckError, Result
from ip.engine.domain.models.stream_definition import StreamDefinition
from ip.engine.ports.outbound.subscribe_transport_port import (
    RawMessageBatchDTO,
    RawMessageDTO,
)


class FakeKafkaClient(KafkaConsumerClientPort):
    def __init__(self, batches: list[list[RawMessageDTO]]) -> None:
        self.batches = batches
        self.committed_messages: list[RawMessageDTO] = []
        self.seek_called = False

    async def test_connection(self) -> Result[None, ConnectionCheckError]:
        return Result.ok(None)

    async def poll_batch(
        self, timeout_ms: int = 1000, max_records: int = 100
    ) -> Sequence[RawMessageDTO]:
        if self.batches:
            return self.batches.pop(0)
        return []

    async def commit_offsets(self, messages: Sequence[RawMessageDTO]) -> None:
        self.committed_messages.extend(messages)

    async def seek_to_uncommitted(self) -> None:
        self.seek_called = True


@pytest.mark.asyncio
async def test_kafka_subscribe_transport_ack_commits_offsets() -> None:
    msg1 = RawMessageDTO(
        message_id="k1", raw_payload=b'{"v":1}', partition_id="0", broker_offset="10"
    )
    client = FakeKafkaClient(batches=[[msg1]])
    transport = KafkaSubscribeTransport(client=client, batch_size=10)

    stop_signal = asyncio.Event()

    async def handler(batch: RawMessageBatchDTO) -> AckVerdict:
        stop_signal.set()
        return AckVerdict.ACK

    stream = StreamDefinition(stream="meters")
    await transport.start_consumer(stream, handler, stop_signal)

    assert len(client.committed_messages) == 1
    assert client.committed_messages[0].message_id == "k1"
    assert client.seek_called is False


@pytest.mark.asyncio
async def test_kafka_subscribe_transport_nack_triggers_seek() -> None:
    msg1 = RawMessageDTO(message_id="k1", raw_payload=b'{"v":1}')
    client = FakeKafkaClient(batches=[[msg1]])
    transport = KafkaSubscribeTransport(client=client, batch_size=10)

    stop_signal = asyncio.Event()

    async def handler(batch: RawMessageBatchDTO) -> AckVerdict:
        stop_signal.set()
        return AckVerdict.NACK

    stream = StreamDefinition(stream="meters")
    await transport.start_consumer(stream, handler, stop_signal)

    assert len(client.committed_messages) == 0
    assert client.seek_called is True


@pytest.mark.asyncio
async def test_kafka_subscribe_transport_reject_commits_offsets() -> None:
    msg1 = RawMessageDTO(message_id="k1", raw_payload=b"INVALID")
    client = FakeKafkaClient(batches=[[msg1]])
    transport = KafkaSubscribeTransport(client=client, batch_size=10)

    stop_signal = asyncio.Event()

    async def handler(batch: RawMessageBatchDTO) -> AckVerdict:
        stop_signal.set()
        return AckVerdict.REJECT

    stream = StreamDefinition(stream="meters")
    await transport.start_consumer(stream, handler, stop_signal)

    assert len(client.committed_messages) == 1
    assert client.seek_called is False


class FakeAmqpHandle(AmqpMessageHandlePort):
    def __init__(self, msg: RawMessageDTO) -> None:
        self._msg = msg
        self.acked = False
        self.nacked = False
        self.rejected = False

    @property
    def message(self) -> RawMessageDTO:
        return self._msg

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, requeue: bool = True) -> None:
        self.nacked = True

    async def reject(self, requeue: bool = False) -> None:
        self.rejected = True


class FakeAmqpClient(AmqpConsumerClientPort):
    def __init__(self, handles: list[FakeAmqpHandle]) -> None:
        self.handles = handles

    async def test_connection(self) -> Result[None, ConnectionCheckError]:
        return Result.ok(None)

    async def fetch_batch(
        self, queue_name: str, batch_size: int, timeout_ms: int = 500
    ) -> Sequence[AmqpMessageHandlePort]:
        if self.handles:
            h = list(self.handles)
            self.handles.clear()
            return h
        return []


@pytest.mark.asyncio
async def test_amqp_subscribe_transport_ack_and_reject() -> None:
    msg = RawMessageDTO(message_id="a1", raw_payload=b"{}")
    h1 = FakeAmqpHandle(msg)
    client = FakeAmqpClient([h1])
    transport = AmqpSubscribeTransport(client=client, queue_name="telemetry_q")

    stop_signal = asyncio.Event()

    async def handler(batch: RawMessageBatchDTO) -> AckVerdict:
        stop_signal.set()
        return AckVerdict.ACK

    stream = StreamDefinition(stream="telemetry")
    await transport.start_consumer(stream, handler, stop_signal)

    assert h1.acked is True
    assert h1.nacked is False
    assert h1.rejected is False


class FakeMqttHandle(MqttMessageHandlePort):
    def __init__(self, msg: RawMessageDTO) -> None:
        self._msg = msg
        self.pubacked = False

    @property
    def message(self) -> RawMessageDTO:
        return self._msg

    async def acknowledge_publish(self) -> None:
        self.pubacked = True


class FakeMqttClient(MqttConsumerClientPort):
    def __init__(self, handles: list[FakeMqttHandle]) -> None:
        self.handles = handles
        self.subscribed_topic: str | None = None
        self.reconnected = False

    async def test_connection(self) -> Result[None, ConnectionCheckError]:
        return Result.ok(None)

    async def subscribe(self, topic: str, qos: int = 1) -> None:
        self.subscribed_topic = topic

    async def fetch_messages(
        self, max_messages: int = 50, timeout_ms: int = 500
    ) -> Sequence[MqttMessageHandlePort]:
        if self.handles:
            h = list(self.handles)
            self.handles.clear()
            return h
        return []

    async def reconnect(self) -> None:
        self.reconnected = True


@pytest.mark.asyncio
async def test_mqtt_subscribe_transport_puback() -> None:
    msg = RawMessageDTO(message_id="m1", raw_payload=b'{"reading":42}')
    h1 = FakeMqttHandle(msg)
    client = FakeMqttClient([h1])
    transport = MqttSubscribeTransport(client=client, topic_filter="grid/meters/+/reading")

    stop_signal = asyncio.Event()

    async def handler(batch: RawMessageBatchDTO) -> AckVerdict:
        stop_signal.set()
        return AckVerdict.ACK

    stream = StreamDefinition(stream="readings")
    await transport.start_consumer(stream, handler, stop_signal)

    assert client.subscribed_topic == "grid/meters/+/reading"
    assert h1.pubacked is True
    assert client.reconnected is False


@pytest.mark.asyncio
async def test_mqtt_subscribe_transport_nack_triggers_reconnect() -> None:
    msg = RawMessageDTO(message_id="m1", raw_payload=b'{"reading":42}')
    h1 = FakeMqttHandle(msg)
    client = FakeMqttClient([h1])
    transport = MqttSubscribeTransport(client=client, topic_filter="grid/meters/+/reading")

    stop_signal = asyncio.Event()

    async def handler(batch: RawMessageBatchDTO) -> AckVerdict:
        stop_signal.set()
        return AckVerdict.NACK

    stream = StreamDefinition(stream="readings")
    await transport.start_consumer(stream, handler, stop_signal)

    assert h1.pubacked is False
    assert client.reconnected is True


@pytest.mark.asyncio
async def test_mqtt_subscribe_transport_reject_pubacks() -> None:
    msg = RawMessageDTO(message_id="m1", raw_payload=b"INVALID")
    h1 = FakeMqttHandle(msg)
    client = FakeMqttClient([h1])
    transport = MqttSubscribeTransport(client=client, topic_filter="grid/meters/+/reading")

    stop_signal = asyncio.Event()

    async def handler(batch: RawMessageBatchDTO) -> AckVerdict:
        stop_signal.set()
        return AckVerdict.REJECT

    stream = StreamDefinition(stream="readings")
    await transport.start_consumer(stream, handler, stop_signal)

    assert h1.pubacked is True
    assert client.reconnected is False


class FakeCloudQueueHandle(CloudQueueMessageHandlePort):
    def __init__(self, msg: RawMessageDTO, receipt: str) -> None:
        self._msg = msg
        self._receipt = receipt

    @property
    def message(self) -> RawMessageDTO:
        return self._msg

    @property
    def receipt_handle(self) -> str:
        return self._receipt


class FakeCloudQueueClient(CloudQueueConsumerClientPort):
    def __init__(self, handles: list[FakeCloudQueueHandle]) -> None:
        self.handles = handles
        self.deleted_receipts: list[str] = []

    async def test_connection(self) -> Result[None, ConnectionCheckError]:
        return Result.ok(None)

    async def receive_messages(
        self, queue_url: str, max_messages: int = 10, wait_time_seconds: int = 20
    ) -> Sequence[CloudQueueMessageHandlePort]:
        if self.handles:
            h = list(self.handles)
            self.handles.clear()
            return h
        return []

    async def delete_batch(self, queue_url: str, receipt_handles: Sequence[str]) -> None:
        self.deleted_receipts.extend(receipt_handles)


@pytest.mark.asyncio
async def test_cloud_queue_subscribe_transport_batch_delete() -> None:
    msg = RawMessageDTO(message_id="sqs_1", raw_payload=b"{}")
    h1 = FakeCloudQueueHandle(msg, receipt="rcpt_001")
    client = FakeCloudQueueClient([h1])
    transport = CloudQueueSubscribeTransport(
        client=client, queue_url="https://sqs.us-east-1.amazonaws.com/123/q"
    )

    stop_signal = asyncio.Event()

    async def handler(batch: RawMessageBatchDTO) -> AckVerdict:
        stop_signal.set()
        return AckVerdict.ACK

    stream = StreamDefinition(stream="events")
    await transport.start_consumer(stream, handler, stop_signal)

    assert client.deleted_receipts == ["rcpt_001"]
