"""Unit tests for KafkaConnector (L5 Destination & Streaming Broker Connector)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pytest
from ip.engine.adapters.outbound.connectors.confluent_kafka_client import (
    build_confluent_kafka_config,
)
from ip.engine.adapters.outbound.connectors.kafka_connector import KafkaConnector
from ip.engine.adapters.outbound.connectors.redpanda_connector import RedpandaConnector
from ip.engine.domain.connection.enums import AuthType, CatalogCategory, EngineConnectorId
from ip.engine.domain.dispatch.enums import FailureDisposition
from ip.engine.domain.exceptions import ConnectionCheckError, KafkaConnectionError, Result
from ip.engine.ports.outbound.connector_port import WriteRecordCommand
from ip.engine.ports.outbound.kafka_client_port import (
    KafkaProducerClientPort,
    KafkaProduceResultDTO,
)
from seedwork.domain.types import JsonDict


class FakeKafkaProducerClient(KafkaProducerClientPort):
    """Test fake implementing KafkaProducerClientPort."""

    def __init__(
        self,
        *,
        fail_check: bool = False,
        fail_produce: bool = False,
        topics: Sequence[str] = ("telemetry.readings.inbound", "system.events"),
    ) -> None:
        self.fail_check = fail_check
        self.fail_produce = fail_produce
        self.topics = list(topics)
        self.produced_messages: list[dict[str, object]] = []

    async def test_connection(self) -> Result[None, ConnectionCheckError]:
        if self.fail_check:
            return Result.fail(ConnectionCheckError(message="Broker unreachable at localhost:9092"))
        return Result.ok(None)

    async def list_topics(self) -> Result[Sequence[str], KafkaConnectionError]:
        return Result.ok(self.topics)

    async def produce(
        self,
        topic: str,
        value: bytes,
        key: bytes | None = None,
        headers: Mapping[str, bytes] | None = None,
        partition: int | None = None,
    ) -> Result[KafkaProduceResultDTO, KafkaConnectionError]:
        if self.fail_produce:
            return Result.fail(
                KafkaConnectionError(
                    bootstrap_servers="localhost:9092",
                    message="Broker closed socket connection unexpectedly",
                    disposition=FailureDisposition.RETRY,
                )
            )

        decoded_headers = {k: v.decode("utf-8") for k, v in (headers or {}).items()}
        decoded_key = key.decode("utf-8") if key is not None else None
        decoded_value = json.loads(value.decode("utf-8"))

        offset = len(self.produced_messages) + 100
        assigned_partition = partition if partition is not None else 0
        record = {
            "topic": topic,
            "key": decoded_key,
            "value": decoded_value,
            "headers": decoded_headers,
            "partition": assigned_partition,
            "offset": offset,
        }
        self.produced_messages.append(record)
        return Result.ok(
            KafkaProduceResultDTO(
                topic=topic,
                partition=assigned_partition,
                offset=offset,
                timestamp_ms=1700000000000,
            )
        )


@pytest.fixture
def fake_producer() -> FakeKafkaProducerClient:
    return FakeKafkaProducerClient()


@pytest.fixture
def connector(fake_producer: FakeKafkaProducerClient) -> KafkaConnector:
    return KafkaConnector(client=fake_producer)


def test_kafka_connector_metadata(connector: KafkaConnector) -> None:
    assert connector.app_id == EngineConnectorId.KAFKA.value
    summary = KafkaConnector.default_catalog_summary()
    assert summary.app_id == EngineConnectorId.KAFKA.value
    assert summary.display_name == "Apache Kafka / Confluent"
    assert summary.category == "MESSAGING"
    assert summary.auth_type == AuthType.NO_AUTH


def test_kafka_connector_spec(connector: KafkaConnector) -> None:
    spec = connector.spec()
    assert spec.app_id == "kafka"
    assert spec.category == "MESSAGING"
    assert spec.auth_type == AuthType.NO_AUTH.value
    property_names = [p.name for p in spec.properties]
    assert "bootstrap_servers" in property_names
    assert "security_protocol" in property_names
    assert "sasl_mechanism" in property_names
    assert "default_topic" in property_names
    assert "partition_key_field" in property_names


@pytest.mark.asyncio
async def test_kafka_check_success(connector: KafkaConnector) -> None:
    public_config = {
        "bootstrap_servers": "localhost:9092",
        "partition_key_field": "meter_serial_number",
    }
    result = await connector.check(public_config, {})
    assert result.success is True
    assert result.status == "SUCCEEDED"
    assert "localhost:9092" in (result.message or "")


@pytest.mark.asyncio
async def test_kafka_check_missing_bootstrap_servers(connector: KafkaConnector) -> None:
    result = await connector.check({}, {})
    assert result.success is False
    assert result.status == "FAILED"
    assert "bootstrap_servers" in (result.message or "")


@pytest.mark.asyncio
async def test_kafka_check_broker_error() -> None:
    failing_client = FakeKafkaProducerClient(fail_check=True)
    failing_connector = KafkaConnector(client=failing_client)
    result = await failing_connector.check({"bootstrap_servers": "localhost:9092"}, {})
    assert result.success is False
    assert "Broker unreachable" in (result.message or "")


@pytest.mark.asyncio
async def test_kafka_discover_topics(connector: KafkaConnector) -> None:
    result = await connector.discover(
        connection_id="conn_kafka_1",
        public_config={"bootstrap_servers": "localhost:9092"},
        credentials={},
        tenant_id="ten_utility_01",
    )
    assert result.success is True
    stream_names = [s.name for s in result.streams]
    assert "telemetry.readings.inbound" in stream_names
    assert "system.events" in stream_names


@pytest.mark.asyncio
async def test_kafka_write_record_success_with_meter_serial_key(
    connector: KafkaConnector,
    fake_producer: FakeKafkaProducerClient,
) -> None:
    payload: JsonDict = {
        "meter_serial_number": "MTR-1001",
        "point_id": "SP-900",
        "reading_timestamp": "2026-10-14T12:00:00Z",
        "kwh_delivered": 14.52,
    }
    command = WriteRecordCommand(
        stream_name="telemetry.readings.inbound",
        operation="CREATE",
        payload=payload,
        headers={
            "x-trace-id": "trc_9988",
            "x-correlation-id": "corr_123",
            "canonical_type": "telemetry.reading_record",
        },
        idempotency_key="idemp_key_1",
    )
    public_config = {
        "bootstrap_servers": "localhost:9092",
        "partition_key_field": "meter_serial_number",
    }

    result = await connector.write_record(
        stream_name="telemetry.readings.inbound",
        command=command,
        public_config=public_config,
        credentials={},
        tenant_id="ten_utility_01",
        connection_id="conn_kafka_mdm",
    )

    assert result.success is True
    assert result.record_id == "MTR-1001"
    assert result.destination_id == "telemetry.readings.inbound:0:100"
    assert result.response_status_code == 200

    assert len(fake_producer.produced_messages) == 1
    produced = fake_producer.produced_messages[0]
    assert produced["topic"] == "telemetry.readings.inbound"
    assert produced["key"] == "MTR-1001"
    assert produced["value"] == payload
    assert produced["headers"]["trace_id"] == "trc_9988"
    assert produced["headers"]["correlation_id"] == "corr_123"
    assert produced["headers"]["tenant_id"] == "ten_utility_01"
    assert produced["headers"]["canonical_type"] == "telemetry.reading_record"
    assert "produced_at" in produced["headers"]


@pytest.mark.asyncio
async def test_kafka_write_record_payload_value_nesting(
    connector: KafkaConnector,
    fake_producer: FakeKafkaProducerClient,
) -> None:
    nested_payload: JsonDict = {
        "key": "MTR-2002",
        "value": {
            "reading_id": "r_123",
            "kwh_delivered": 42.0,
        },
    }
    command = WriteRecordCommand(
        stream_name="telemetry.readings.inbound",
        operation="CREATE",
        payload=nested_payload,
        record_id="MTR-2002",
    )
    result = await connector.write_record(
        stream_name="telemetry.readings.inbound",
        command=command,
        public_config={"bootstrap_servers": "localhost:9092"},
        credentials={},
        tenant_id="ten_utility_01",
    )
    assert result.success is True
    assert result.record_id == "MTR-2002"
    assert fake_producer.produced_messages[0]["key"] == "MTR-2002"
    assert fake_producer.produced_messages[0]["value"] == {
        "reading_id": "r_123",
        "kwh_delivered": 42.0,
    }


@pytest.mark.asyncio
async def test_kafka_write_record_error_classification() -> None:
    failing_client = FakeKafkaProducerClient(fail_produce=True)
    failing_connector = KafkaConnector(client=failing_client)
    command = WriteRecordCommand(
        stream_name="telemetry.readings.inbound",
        operation="CREATE",
        payload={"meter_serial_number": "MTR-3003"},
    )
    result = await failing_connector.write_record(
        stream_name="telemetry.readings.inbound",
        command=command,
        public_config={"bootstrap_servers": "localhost:9092"},
        credentials={},
        tenant_id="ten_utility_01",
    )
    assert result.success is False
    assert result.failure_category == "TRANSIENT"
    assert "Broker closed socket" in (result.error_message or "")


def test_redpanda_connector_specification() -> None:
    summary = RedpandaConnector.default_catalog_summary()
    assert summary.app_id == "redpanda"
    assert summary.display_name == "Redpanda"
    assert summary.category == CatalogCategory.MESSAGING

    connector = RedpandaConnector()
    assert connector.app_id == "redpanda"
    assert RedpandaConnector.default_catalog_summary().auth_type == AuthType.NO_AUTH

    spec = connector.spec()
    assert spec.app_id == "redpanda"
    assert spec.display_name == "Redpanda"
    assert spec.auth_type == AuthType.NO_AUTH.value
    prop_names = {p.name for p in spec.properties}
    assert "bootstrap_servers" in prop_names
    assert "security_protocol" in prop_names
    assert "schema_registry_url" in prop_names
    schema_prop = next(p for p in spec.properties if p.name == "schema_registry_url")
    assert schema_prop.default == "http://localhost:8081"
    assert schema_prop.required is False


def test_build_confluent_kafka_config_translates_properties() -> None:
    conf = build_confluent_kafka_config(
        public_config={
            "bootstrap_servers": "broker1:9092,broker2:9092",
            "client_id": "test-ami-producer",
            "security_protocol": "SASL_SSL",
            "sasl_mechanism": "SCRAM-SHA-512",
            "compression_type": "lz4",
            "acks": "all",
            "retries": 10,
        },
        credentials={
            "username": "utility_user",
            "password": "secret_password",
            "ssl_ca_cert": "/path/to/ca.pem",
        },
    )

    assert conf["bootstrap.servers"] == "broker1:9092,broker2:9092"
    assert conf["client.id"] == "test-ami-producer"
    assert conf["security.protocol"] == "SASL_SSL"
    assert conf["sasl.mechanism"] == "SCRAM-SHA-512"
    assert conf["sasl.username"] == "utility_user"
    assert conf["sasl.password"] == "secret_password"
    assert conf["ssl.ca.location"] == "/path/to/ca.pem"
    assert conf["compression.type"] == "lz4"
    assert conf["acks"] == "all"
    assert conf["enable.idempotence"] is True
    assert conf["retries"] == 10
