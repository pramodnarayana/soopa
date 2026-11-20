"""Passive Inbound Webhook Connector for the Integration Platform."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from typing import ClassVar

from ip.engine.adapters.outbound.connectors.base_connector import BaseConnector
from ip.engine.domain.connection.enums import (
    AuthType,
    CatalogCategory,
    ConnectorArchitectureType,
    ConnectorPropertyKey,
    ConnectorRole,
    EngineConnectorId,
    PropertyType,
    WebhookModality,
)
from ip.engine.domain.exceptions import InvalidConnectionConfigError
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
from seedwork.domain.types import JsonDict


class WebhookConnector(BaseConnector):
    """Passive Inbound HTTP Ingress Gateway Connector for receiving external push webhooks."""

    _SLUG_REGEX: ClassVar[re.Pattern[str]] = re.compile(r"^[a-z0-9_-]+$")

    @classmethod
    def default_catalog_summary(cls) -> CatalogAppSummaryDTO:
        return CatalogAppSummaryDTO(
            app_id=EngineConnectorId.WEBHOOK,
            display_name="Webhook",
            category=CatalogCategory.API,
            auth_type=AuthType.CUSTOM,
            description="Passive HTTP ingress gateway receiving external push events and webhooks.",
            connector_type=ConnectorArchitectureType.DECLARATIVE_HTTP,
            role=ConnectorRole.INBOUND_GATEWAY.value,
        )

    @property
    def app_id(self) -> str:
        return EngineConnectorId.WEBHOOK.value

    def spec(self) -> AppSpecDTO:
        return AppSpecDTO(
            app_id=EngineConnectorId.WEBHOOK.value,
            display_name="Webhook",
            auth_type=AuthType.CUSTOM.value,
            category=CatalogCategory.API.value,
            description="Passive HTTP ingress gateway receiving external push events and webhooks into the Integration Platform.",
            role=ConnectorRole.INBOUND_GATEWAY.value,
            properties=(
                ConnectorPropertyDTO(
                    name=ConnectorPropertyKey.WEBHOOK_MODALITY.value,
                    label="Webhook Modality",
                    type=PropertyType.DROPDOWN.value,
                    required=True,
                    default=WebhookModality.DYNAMIC.value,
                    description="Execution path: Operational Command (L4 Orchestration), Data Ingestion (L1-L3 Hub), or Dynamic.",
                    options=(
                        DropdownOptionDTO(
                            label="Dynamic / Multiplexed (Header / Query / Body auto-detected)",
                            value=WebhookModality.DYNAMIC.value,
                        ),
                        DropdownOptionDTO(
                            label="Operational Command (Triggers L4 Orchestration — Bypasses L2 & L3)",
                            value=WebhookModality.COMMAND.value,
                        ),
                        DropdownOptionDTO(
                            label="Data Ingestion (Streams into L1 -> L2 -> L3 Canonical Tables)",
                            value=WebhookModality.DATA.value,
                        ),
                    ),
                ),
                ConnectorPropertyDTO(
                    name=ConnectorPropertyKey.VERIFICATION_STRATEGY.value,
                    label="Verification Strategy",
                    type=PropertyType.DROPDOWN.value,
                    required=True,
                    default="HMAC_SHA256",
                    description="Cryptographic signature or perimeter authentication strategy for incoming webhooks.",
                    options=(
                        DropdownOptionDTO(
                            label="HMAC SHA-256 (Payload Signature)",
                            value="HMAC_SHA256",
                        ),
                        DropdownOptionDTO(
                            label="Bearer Token (Authorization Header)",
                            value="BEARER_TOKEN",
                        ),
                        DropdownOptionDTO(
                            label="Shared Header Secret (X-Webhook-Secret / API Key)",
                            value="SHARED_HEADER_SECRET",
                        ),
                        DropdownOptionDTO(
                            label="Mutual TLS (mTLS Client Certificate)",
                            value="MUTUAL_TLS",
                        ),
                        DropdownOptionDTO(
                            label="Open / Public (Unauthenticated)",
                            value="PUBLIC_UNAUTHENTICATED",
                        ),
                    ),
                ),
                ConnectorPropertyDTO(
                    name=ConnectorPropertyKey.SECRET_TOKEN.value,
                    label="Secret Token / Key",
                    type=PropertyType.SECRET_TEXT.value,
                    required=False,
                    description="Shared secret key used to verify incoming webhook signatures or auth headers.",
                ),
                ConnectorPropertyDTO(
                    name=ConnectorPropertyKey.ENDPOINT_SLUG.value,
                    label="Webhook URL",
                    type=PropertyType.SHORT_TEXT.value,
                    required=True,
                    description="Full ingress URL where external systems send HTTP POST webhooks.",
                ),
            ),
        )

    async def check(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> ConnectionCheckResultDTO:
        _ = credentials
        raw_slug = (
            str(public_config.get(ConnectorPropertyKey.ENDPOINT_SLUG.value, "")).strip().lower()
        )
        if not raw_slug:
            return ConnectionCheckResultDTO.from_error(
                InvalidConnectionConfigError(
                    field_name=ConnectorPropertyKey.ENDPOINT_SLUG.value,
                    message="Endpoint slug is required.",
                )
            )

        if not self._SLUG_REGEX.match(raw_slug):
            return ConnectionCheckResultDTO.from_error(
                InvalidConnectionConfigError(
                    field_name=ConnectorPropertyKey.ENDPOINT_SLUG.value,
                    message="Endpoint slug may only contain lowercase letters, numbers, hyphens, and underscores.",
                )
            )

        return ConnectionCheckResultDTO.ok(
            f"Ingress endpoint slug '{raw_slug}' is valid and ready to receive events."
        )

    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
        *,
        tenant_id: str,
    ) -> DiscoveredCatalogDTO:
        _ = (public_config, credentials, tenant_id)
        default_streams = (
            StreamSchemaDTO(
                name="events",
                fields=(
                    StreamFieldDTO(name="record_id", data_type="string", nullable=False),
                    StreamFieldDTO(name="payload", data_type="json", nullable=False),
                    StreamFieldDTO(name="headers", data_type="json", nullable=True),
                    StreamFieldDTO(name="received_at", data_type="string", nullable=False),
                ),
                primary_key=("record_id",),
                cursor_field="received_at",
            ),
        )
        return self.build_catalog_dto(connection_id, default_streams)

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
        _ = (stream_name, public_config, credentials, limit, cursor, tenant_id, connection_id)
        return ["events"]

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
        _ = (stream_name, public_config, credentials, tenant_id, connection_id)
        err = InvalidConnectionConfigError(
            field_name="app_id",
            message="Webhook connector is a passive ingress gateway and does not support active outbound delivery.",
        )
        return WriteResultDTO.from_error(
            err,
            record_id=command.record_id or "",
            target_url="webhook://ingress",
            http_method="POST",
        )


__all__ = ["WebhookConnector"]
