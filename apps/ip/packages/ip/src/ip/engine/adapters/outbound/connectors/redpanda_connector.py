"""Native Redpanda Destination & Streaming Connector for the Integration Platform."""

from __future__ import annotations

from ip.engine.adapters.outbound.connectors.kafka_connector import KafkaConnector
from ip.engine.domain.connection.enums import (
    AuthType,
    CatalogCategory,
    ConnectorArchitectureType,
    EngineConnectorId,
    PropertyType,
)
from ip.engine.ports.outbound.catalog_registry_port import CatalogAppSummaryDTO
from ip.engine.ports.outbound.connector_port import (
    AppSpecDTO,
    ConnectorPropertyDTO,
)
from ip.engine.ports.outbound.kafka_client_port import (
    KafkaProducerClientFactoryPort,
    KafkaProducerClientPort,
)


class RedpandaConnector(KafkaConnector):
    """Native Redpanda Protocol Connector for high-throughput event streaming."""

    @classmethod
    def default_catalog_summary(cls) -> CatalogAppSummaryDTO:
        return CatalogAppSummaryDTO(
            app_id=EngineConnectorId.REDPANDA,
            display_name="Redpanda",
            category=CatalogCategory.MESSAGING,
            auth_type=AuthType.NO_AUTH,
            description="High-performance, C++ Kafka API-compatible distributed streaming data platform.",
            connector_type=ConnectorArchitectureType.NATIVE_PROTOCOL,
        )

    def __init__(
        self,
        client: KafkaProducerClientPort | None = None,
        client_factory: KafkaProducerClientFactoryPort | None = None,
        *,
        default_timeout_seconds: float = 15.0,
    ) -> None:
        super().__init__(
            client=client,
            client_factory=client_factory,
            default_timeout_seconds=default_timeout_seconds,
        )

    @property
    def app_id(self) -> str:
        return EngineConnectorId.REDPANDA.value

    def spec(self) -> AppSpecDTO:
        base_spec = super().spec()
        schema_registry_prop = ConnectorPropertyDTO(
            name="schema_registry_url",
            label="Redpanda Schema Registry URL",
            type=PropertyType.SHORT_TEXT.value,
            required=False,
            default="http://localhost:8081",
            description="Built-in Redpanda Schema Registry REST endpoint for Avro/JSON schema management",
        )
        return AppSpecDTO(
            app_id=EngineConnectorId.REDPANDA.value,
            display_name="Redpanda",
            auth_type=AuthType.NO_AUTH.value,
            category=CatalogCategory.MESSAGING.value,
            description="High-performance, C++ Kafka API-compatible event streaming platform.",
            properties=(*base_spec.properties, schema_registry_prop),
        )


__all__ = ["RedpandaConnector"]
