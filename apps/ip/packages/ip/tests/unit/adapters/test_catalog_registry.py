"""Unit tests for ConnectorCatalogRegistry."""

from __future__ import annotations

import pytest
from ip.engine.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.engine.domain.exceptions import ConnectorNotFoundError
from ip.engine.domain.models.connector_spec import (
    ConnectorPropertySchema,
    DeclarativeManifest,
    HttpActionSpec,
)


@pytest.mark.asyncio
async def test_generic_registry_registration_and_unregistration() -> None:
    registry = ConnectorCatalogRegistry()
    assert len(registry.list_apps()) == 0

    schema = ConnectorPropertySchema(
        app_id="custom_crm",
        display_name="Custom Enterprise CRM",
        auth_type="API_KEY",
        category="CRM",
        description="Dynamic custom connector",
        properties=(),
    )
    manifest = DeclarativeManifest(
        app_id="custom_crm",
        display_name="Custom Enterprise CRM",
        category="CRM",
        auth_type="API_KEY",
        base_url_template="https://api.custom.com",
        property_schema=schema,
        check_action=HttpActionSpec(path="/ping", method="GET"),
        streams={},
    )
    registry.register_manifest(manifest)
    assert len(registry.list_apps()) == 1
    spec_res = registry.get_app_spec("custom_crm")
    assert spec_res.is_ok is True
    assert spec_res.value is not None
    assert spec_res.value.display_name == "Custom Enterprise CRM"

    connector_res = registry.get_connector("custom_crm")
    assert connector_res.is_ok is True
    assert connector_res.value is not None
    assert connector_res.value.app_id == "custom_crm"

    registry.unregister("custom_crm")
    assert len(registry.list_apps()) == 0
    missing_res = registry.get_connector("custom_crm")
    assert missing_res.is_err is True
    assert isinstance(missing_res.error, ConnectorNotFoundError)
