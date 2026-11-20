"""Unit tests for WebhookConnector (Passive Inbound Webhook Connector)."""

from __future__ import annotations

import pytest
from ip.engine.adapters.outbound.connectors.webhook_connector import WebhookConnector
from ip.engine.bootstrap.container import create_engine_catalog_registry
from ip.engine.domain.connection.enums import (
    AuthType,
    CatalogCategory,
    ConnectorRole,
    EngineConnectorId,
)
from ip.engine.ports.outbound.connector_port import WriteRecordCommand


def test_webhook_connector_default_catalog_summary() -> None:
    summary = WebhookConnector.default_catalog_summary()
    assert summary.app_id == EngineConnectorId.WEBHOOK.value
    assert summary.display_name == "Webhook"
    assert summary.category == CatalogCategory.API.value
    assert summary.auth_type == AuthType.CUSTOM.value
    assert summary.role == ConnectorRole.INBOUND_GATEWAY.value


def test_webhook_connector_spec() -> None:
    connector = WebhookConnector()
    spec = connector.spec()

    assert spec.app_id == EngineConnectorId.WEBHOOK.value
    assert spec.display_name == "Webhook"
    assert spec.category == CatalogCategory.API.value
    assert spec.role == ConnectorRole.INBOUND_GATEWAY.value

    prop_names = [p.name for p in spec.properties]
    assert "endpoint_slug" in prop_names
    assert "verification_strategy" in prop_names
    assert "secret_token" in prop_names
    assert "description" not in prop_names

    slug_prop = next(p for p in spec.properties if p.name == "endpoint_slug")
    assert slug_prop.required is True
    assert slug_prop.label == "Webhook URL"
    assert spec.properties[-1].name == "endpoint_slug"

    strat_prop = next(p for p in spec.properties if p.name == "verification_strategy")
    assert strat_prop.required is True
    assert strat_prop.default == "HMAC_SHA256"
    assert len(strat_prop.options) >= 5


@pytest.mark.asyncio
async def test_webhook_connector_check_rejects_missing_slug() -> None:
    connector = WebhookConnector()
    result = await connector.check(public_config={}, credentials={})

    assert result.success is False
    assert result.status == "FAILED"
    assert result.error is not None
    assert "Endpoint slug is required" in result.error.message


@pytest.mark.asyncio
async def test_webhook_connector_check_rejects_invalid_slug() -> None:
    connector = WebhookConnector()
    result = await connector.check(
        public_config={"endpoint_slug": "invalid slug with spaces!"},
        credentials={},
    )

    assert result.success is False
    assert result.status == "FAILED"
    assert "lowercase letters, numbers, hyphens" in (result.message or "")


@pytest.mark.asyncio
async def test_webhook_connector_check_accepts_valid_slug() -> None:
    connector = WebhookConnector()
    result = await connector.check(
        public_config={"endpoint_slug": "partner-ingress_v1"},
        credentials={},
    )

    assert result.success is True
    assert result.status == "SUCCEEDED"
    assert "partner-ingress_v1" in (result.message or "")


@pytest.mark.asyncio
async def test_webhook_connector_discover() -> None:
    connector = WebhookConnector()
    catalog = await connector.discover(
        connection_id="conn_webhook_123",
        public_config={"endpoint_slug": "partner-ingress"},
        credentials={},
        tenant_id="tenant_power",
    )

    assert catalog.success is True
    assert catalog.connection_id == "conn_webhook_123"
    assert len(catalog.streams) == 1
    assert catalog.streams[0].name == "events"
    assert catalog.catalog_hash != ""


def test_create_engine_catalog_registry_includes_webhook() -> None:
    registry = create_engine_catalog_registry(allow_private_ips=True)
    all_apps = registry.list_apps()
    app_ids = {a.app_id for a in all_apps}

    assert EngineConnectorId.WEBHOOK.value in app_ids
    webhook_summary = next(a for a in all_apps if a.app_id == EngineConnectorId.WEBHOOK.value)
    assert webhook_summary.display_name == "Webhook"
    assert webhook_summary.role == ConnectorRole.INBOUND_GATEWAY.value


@pytest.mark.asyncio
async def test_webhook_connector_write_record_rejects_active_outbound_delivery() -> None:
    connector = WebhookConnector()
    cmd = WriteRecordCommand(
        stream_name="events",
        operation="CREATE",
        payload={"foo": "bar"},
        record_id="rec_123",
    )
    result = await connector.write_record(
        stream_name="events",
        command=cmd,
        public_config={"endpoint_slug": "partner-ingress"},
        credentials={},
    )

    assert result.success is False
    assert result.error is not None
    assert "passive ingress gateway" in result.error.message
