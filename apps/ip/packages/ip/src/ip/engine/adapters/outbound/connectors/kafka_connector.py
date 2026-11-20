"""Native Apache Kafka / Confluent Destination & Streaming Connector for the Integration Platform."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import structlog
from ip.engine.adapters.outbound.connectors.base_connector import BaseConnector
from ip.engine.domain.connection.enums import (
    AuthType,
    CatalogCategory,
    ConnectorArchitectureType,
    ConnectorPropertyKey,
    EngineConnectorId,
    PropertyType,
)
from ip.engine.domain.dispatch.enums import FailureDisposition
from ip.engine.domain.exceptions import (
    ConnectionCheckError,
    InvalidConnectionConfigError,
    KafkaConnectionError,
    Result,
)
from ip.engine.ports.outbound.catalog_registry_port import CatalogAppSummaryDTO
from ip.engine.ports.outbound.connector_port import (
    AppSpecDTO,
    ConnectionCheckResultDTO,
    ConnectorPropertyDTO,
    DiscoveredCatalogDTO,
    DropdownOptionDTO,
    RecordEnvelopeDTO,
    StreamFieldDTO,
    StreamSchemaDTO,
    WriteRecordCommand,
    WriteResultDTO,
)
from ip.engine.ports.outbound.kafka_client_port import (
    KafkaProducerClientFactoryPort,
    KafkaProducerClientPort,
)
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


def _extract_header(
    command: WriteRecordCommand, primary: str | None, *fallback_keys: str
) -> str | None:
    if primary:
        return primary
    for k in fallback_keys:
        val = command.headers.get(k)
        if val is not None and str(val).strip():
            return str(val)
    return None


class KafkaConnector(BaseConnector):
    """Native Protocol Connector for producing and streaming events over Apache Kafka."""

    @classmethod
    def default_catalog_summary(cls) -> CatalogAppSummaryDTO:
        return CatalogAppSummaryDTO(
            app_id=EngineConnectorId.KAFKA,
            display_name="Apache Kafka / Confluent",
            category=CatalogCategory.MESSAGING,
            auth_type=AuthType.NO_AUTH,
            description="Enterprise distributed streaming message broker connector for high-throughput event streaming.",
            connector_type=ConnectorArchitectureType.NATIVE_PROTOCOL,
        )

    def __init__(
        self,
        client: KafkaProducerClientPort | None = None,
        client_factory: KafkaProducerClientFactoryPort | None = None,
        *,
        default_timeout_seconds: float = 15.0,
    ) -> None:
        self._client = client
        self._client_factory = client_factory
        self._default_timeout_seconds = default_timeout_seconds

    @property
    def app_id(self) -> str:
        return EngineConnectorId.KAFKA.value

    def spec(self) -> AppSpecDTO:
        return AppSpecDTO(
            app_id=EngineConnectorId.KAFKA.value,
            display_name="Apache Kafka / Confluent",
            auth_type=AuthType.NO_AUTH.value,
            category=CatalogCategory.MESSAGING.value,
            description="Enterprise distributed event streaming connector for Apache Kafka and Confluent Platform.",
            properties=(
                ConnectorPropertyDTO(
                    name="bootstrap_servers",
                    label="Bootstrap Servers",
                    type=PropertyType.SHORT_TEXT.value,
                    required=True,
                    description="Comma-separated broker host:port addresses (e.g. kafka.internal:9092,kafka2.internal:9092)",
                ),
                ConnectorPropertyDTO(
                    name="security_protocol",
                    label="Security Protocol",
                    type=PropertyType.DROPDOWN.value,
                    required=True,
                    default="PLAINTEXT",
                    description="Network protocol used to communicate with brokers",
                    options=(
                        DropdownOptionDTO(label="PLAINTEXT (Unencrypted)", value="PLAINTEXT"),
                        DropdownOptionDTO(
                            label="SASL_PLAINTEXT (SASL Unencrypted)", value="SASL_PLAINTEXT"
                        ),
                        DropdownOptionDTO(label="SASL_SSL (SASL Encrypted)", value="SASL_SSL"),
                        DropdownOptionDTO(label="SSL (TLS Mutual Auth)", value="SSL"),
                    ),
                ),
                ConnectorPropertyDTO(
                    name="sasl_mechanism",
                    label="SASL Mechanism",
                    type=PropertyType.DROPDOWN.value,
                    required=False,
                    default="PLAIN",
                    description="SASL authentication mechanism",
                    options=(
                        DropdownOptionDTO(label="PLAIN", value="PLAIN"),
                        DropdownOptionDTO(label="SCRAM-SHA-256", value="SCRAM-SHA-256"),
                        DropdownOptionDTO(label="SCRAM-SHA-512", value="SCRAM-SHA-512"),
                        DropdownOptionDTO(label="GSSAPI (Kerberos)", value="GSSAPI"),
                        DropdownOptionDTO(label="OAUTHBEARER", value="OAUTHBEARER"),
                    ),
                ),
                ConnectorPropertyDTO(
                    name="username",
                    label="SASL Username / API Key",
                    type=PropertyType.SECRET_TEXT.value,
                    required=False,
                    description="Username or Confluent API Key",
                ),
                ConnectorPropertyDTO(
                    name="password",
                    label="SASL Password / Secret",
                    type=PropertyType.SECRET_TEXT.value,
                    required=False,
                    description="Password or Confluent API Secret",
                ),
                ConnectorPropertyDTO(
                    name="default_topic",
                    label="Default Topic",
                    type=PropertyType.SHORT_TEXT.value,
                    required=False,
                    description="Default topic name to produce records to if stream name is omitted",
                ),
                ConnectorPropertyDTO(
                    name="client_id",
                    label="Client ID",
                    type=PropertyType.SHORT_TEXT.value,
                    required=False,
                    default="soopa-ip-kafka",
                    description="Client identifier passed to Kafka brokers for tracking",
                ),
                ConnectorPropertyDTO(
                    name="partition_key_field",
                    label="Partition Key Field",
                    type=PropertyType.SHORT_TEXT.value,
                    required=False,
                    default="id",
                    description="JSON payload field extracted as Kafka message partition key",
                ),
            ),
        )

    def _resolve_producer(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> Result[KafkaProducerClientPort, KafkaConnectionError]:
        if self._client is not None:
            return Result.ok(self._client)
        if self._client_factory is None:
            return Result.fail(
                KafkaConnectionError(
                    bootstrap_servers=str(public_config.get("bootstrap_servers", "")),
                    message="No Kafka producer client or factory configured on KafkaConnector.",
                )
            )
        try:
            resolved = self._client_factory.create_producer(public_config, credentials)
            return Result.ok(resolved)
        except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as exc:
            return Result.fail(
                KafkaConnectionError(
                    bootstrap_servers=str(public_config.get("bootstrap_servers", "")),
                    message=f"Failed to instantiate Kafka producer client: {exc}",
                )
            )

    async def check(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> ConnectionCheckResultDTO:
        servers = str(public_config.get("bootstrap_servers", "")).strip()
        if not servers:
            return ConnectionCheckResultDTO.from_error(
                InvalidConnectionConfigError(
                    field_name="bootstrap_servers",
                    message="Missing required 'bootstrap_servers' parameter.",
                )
            )

        client_res = self._resolve_producer(public_config, credentials)
        if client_res.is_err or client_res.value is None:
            err = client_res.error or ConnectionCheckError(
                message=f"Kafka producer client resolution failed for brokers '{servers}'."
            )
            return ConnectionCheckResultDTO.from_error(err)

        client = client_res.value
        test_res = await client.test_connection()
        if test_res.is_err:
            err = test_res.unwrap_err()
            return ConnectionCheckResultDTO.from_error(err)

        return ConnectionCheckResultDTO.ok(
            f"Successfully connected to Kafka brokers at '{servers}'."
        )

    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
        *,
        tenant_id: str,
    ) -> DiscoveredCatalogDTO:
        _ = tenant_id
        client_res = self._resolve_producer(public_config, credentials)
        if client_res.is_err or client_res.value is None:
            err = client_res.error or KafkaConnectionError(
                bootstrap_servers=str(public_config.get("bootstrap_servers", "")),
                message="Failed to resolve Kafka client for catalog discovery.",
            )
            return DiscoveredCatalogDTO.from_error(connection_id, err)

        client = client_res.value
        topics_res = await client.list_topics()
        if topics_res.is_err or topics_res.value is None:
            err = topics_res.error or KafkaConnectionError(
                bootstrap_servers=str(
                    public_config.get(ConnectorPropertyKey.BOOTSTRAP_SERVERS, "")
                ),
                message="Failed to query cluster topics from Kafka.",
            )
            logger.error(
                "kafka_discover_topics_failed",
                connection_id=connection_id,
                error=err.message,
            )
            return DiscoveredCatalogDTO.from_error(connection_id, err)

        topics = topics_res.value
        streams: list[StreamSchemaDTO] = []
        for topic in sorted(topics):
            streams.append(
                StreamSchemaDTO(
                    name=topic,
                    fields=(
                        StreamFieldDTO(
                            name="key",
                            data_type="string",
                            nullable=True,
                            description="Kafka partition key",
                        ),
                        StreamFieldDTO(
                            name="value",
                            data_type="json",
                            nullable=False,
                            description="Message payload body",
                        ),
                        StreamFieldDTO(
                            name="headers",
                            data_type="json",
                            nullable=True,
                            description="Kafka record headers",
                        ),
                    ),
                    primary_key=("key",),
                    cursor_field="offset",
                    supported_sync_modes=("FULL_REFRESH", "INCREMENTAL"),
                )
            )

        return self.build_catalog_dto(connection_id, streams)

    def _extract_destination_topic(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
    ) -> str:
        if stream_name and stream_name.strip() and stream_name.strip().lower() != "default":
            return stream_name.strip()
        payload_dest = command.payload.get("destination")
        if isinstance(payload_dest, dict):
            dest_topic = payload_dest.get("topic")
            if isinstance(dest_topic, str) and dest_topic.strip():
                return dest_topic.strip()
        default_topic = public_config.get("default_topic")
        if isinstance(default_topic, str) and default_topic.strip():
            return default_topic.strip()
        return stream_name.strip() or "default"

    def _extract_partition_key(
        self,
        command: WriteRecordCommand,
        public_config: JsonDict,
    ) -> str | None:
        if command.record_id and command.record_id.strip():
            return command.record_id.strip()
        if "key" in command.payload and command.payload["key"] is not None:
            return str(command.payload["key"]).strip()
        key_field = str(public_config.get("partition_key_field") or "id")
        candidate = command.payload.get(key_field)
        if candidate is not None:
            return str(candidate).strip()
        # Fallbacks for standard entity schemas
        for alt_field in (
            "id",
            "record_id",
            "entity_id",
            "external_id",
            "key",
        ):
            val = command.payload.get(alt_field)
            if val is not None:
                return str(val).strip()
        return None

    def _extract_value_payload(self, command: WriteRecordCommand) -> JsonDict:
        val = command.payload.get("value")
        if isinstance(val, dict):
            return val
        return command.payload

    def _build_kafka_headers(
        self,
        command: WriteRecordCommand,
        tenant_id: str,
    ) -> dict[str, bytes]:
        headers: dict[str, bytes] = {}
        trace_id = _extract_header(command, command.trace_id, "x-trace-id", "trace_id")
        if trace_id:
            headers["trace_id"] = trace_id.encode("utf-8")

        corr_id = _extract_header(
            command, command.correlation_id, "x-correlation-id", "correlation_id"
        )
        if corr_id:
            headers["correlation_id"] = corr_id.encode("utf-8")

        if tenant_id:
            headers["tenant_id"] = tenant_id.encode("utf-8")

        canon = _extract_header(command, None, "canonical_type", "x-canonical-type")
        if canon:
            headers["canonical_type"] = canon.encode("utf-8")

        headers["produced_at"] = datetime.now(UTC).isoformat().encode("utf-8")
        if command.idempotency_key:
            headers[command.idempotency_header_name] = str(command.idempotency_key).encode("utf-8")

        reserved = {
            "trace_id",
            "x-trace-id",
            "correlation_id",
            "x-correlation-id",
            "tenant_id",
            "canonical_type",
            "x-canonical-type",
        }
        for k, v in command.headers.items():
            if k.lower() not in reserved:
                headers[k] = str(v).encode("utf-8")
        return headers

    async def write_record(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
        credentials: JsonDict,
        *,
        tenant_id: str = "",
        connection_id: str = "",
    ) -> WriteResultDTO:
        started_at = time.perf_counter()
        topic = self._extract_destination_topic(stream_name, command, public_config)
        key_str = self._extract_partition_key(command, public_config)
        key_bytes = key_str.encode("utf-8") if key_str else None
        target_url = f"kafka://{topic}"

        client_res = self._resolve_producer(public_config, credentials)
        if client_res.is_err or client_res.value is None:
            duration_ms = max(1, int((time.perf_counter() - started_at) * 1000))
            err = client_res.error or KafkaConnectionError(
                bootstrap_servers=str(public_config.get("bootstrap_servers", "")),
                message="Failed to resolve Kafka producer client.",
            )
            return WriteResultDTO.from_error(
                err,
                record_id=key_str or "unresolved",
                target_url=target_url,
                http_method="PRODUCE",
                duration_ms=duration_ms,
                failure_category="TERMINAL",
            )

        client = client_res.value
        headers = self._build_kafka_headers(command, tenant_id)
        payload_data = self._extract_value_payload(command)
        value_bytes = json.dumps(payload_data, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )

        produce_res = await client.produce(
            topic=topic,
            value=value_bytes,
            key=key_bytes,
            headers=headers,
        )
        duration_ms = max(1, int((time.perf_counter() - started_at) * 1000))
        if produce_res.is_err or produce_res.value is None:
            err = produce_res.error or KafkaConnectionError(
                bootstrap_servers=str(
                    public_config.get(ConnectorPropertyKey.BOOTSTRAP_SERVERS, "")
                ),
                message=f"Kafka produce failed on topic '{topic}'",
                disposition=FailureDisposition.RETRY,
            )
            logger.error(
                "kafka_record_produce_failed",
                tenant_id=tenant_id,
                connection_id=connection_id,
                topic=topic,
                key=key_str,
                error=err.message,
                duration_ms=duration_ms,
            )
            return WriteResultDTO.from_error(
                err,
                record_id=key_str or "failed",
                target_url=target_url,
                http_method="PRODUCE",
                duration_ms=duration_ms,
                failure_category="TRANSIENT",
            )

        res = produce_res.value
        dest_id = f"{res.topic}:{res.partition}:{res.offset}"
        logger.info(
            "kafka_record_produced_successfully",
            tenant_id=tenant_id,
            connection_id=connection_id,
            topic=res.topic,
            partition=res.partition,
            offset=res.offset,
            key=key_str,
            duration_ms=duration_ms,
        )
        return WriteResultDTO(
            success=True,
            record_id=key_str or str(res.offset),
            destination_id=dest_id,
            target_url=target_url,
            http_method="PRODUCE",
            duration_ms=duration_ms,
            response_status_code=200,
            response_body={
                "topic": res.topic,
                "partition": res.partition,
                "offset": res.offset,
                "timestamp_ms": res.timestamp_ms,
            },
        )

    async def list_objects(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        limit: int = 100,
        cursor: str | None = None,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> Sequence[str]:
        _ = (limit, cursor, tenant_id, connection_id)
        catalog = await self.discover(
            connection_id=connection_id,
            public_config=public_config,
            credentials=credentials,
            tenant_id=tenant_id,
        )
        return [s.name for s in catalog.streams]

    async def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
        *,
        tenant_id: str,
        connection_id: str,
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        _ = (stream_name, public_config, credentials, cursor, limit, tenant_id, connection_id)
        if False:
            yield RecordEnvelopeDTO(stream_name="", record_id="", data={}, emitted_at="")


__all__ = ["KafkaConnector"]
