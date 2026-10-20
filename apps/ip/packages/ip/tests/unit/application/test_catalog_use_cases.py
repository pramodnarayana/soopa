"""Unit tests for catalog application use cases."""

from __future__ import annotations

import pytest
from ip.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.adapters.outbound.connectors.registry_loader import create_default_catalog_registry
from ip.application.catalog.get_app_spec_use_case import (
    GetAppSpecQuery,
    GetAppSpecUseCase,
)
from ip.application.catalog.list_catalog_apps_use_case import (
    ListCatalogAppsQuery,
    ListCatalogAppsUseCase,
)
from ip.domain.exceptions import ConnectorNotFoundException
from ip.domain.models.connector_spec import (
    ConnectorPropertySchema,
    DeclarativeManifest,
    HttpActionSpec,
)


@pytest.fixture
def catalog_registry() -> ConnectorCatalogRegistry:
    return create_default_catalog_registry()


@pytest.mark.asyncio
async def test_list_catalog_apps_use_case(catalog_registry: ConnectorCatalogRegistry) -> None:
    use_case = ListCatalogAppsUseCase(registry=catalog_registry)
    all_apps = await use_case.execute(ListCatalogAppsQuery())
    assert len(all_apps) >= 5

    crm_apps = await use_case.execute(ListCatalogAppsQuery(category="CRM"))
    for a in crm_apps:
        assert a.category == "CRM"

    stripe_apps = await use_case.execute(ListCatalogAppsQuery(search="stripe"))
    assert len(stripe_apps) == 1
    assert stripe_apps[0].app_id == "stripe"


@pytest.mark.asyncio
async def test_get_app_spec_use_case(catalog_registry: ConnectorCatalogRegistry) -> None:
    use_case = GetAppSpecUseCase(registry=catalog_registry)
    spec = await use_case.execute(GetAppSpecQuery(app_id="salesforce"))
    assert spec.app_id == "salesforce"
    assert spec.display_name == "Salesforce CRM"
    assert len(spec.properties) > 0


@pytest.mark.asyncio
async def test_get_app_spec_use_case_not_found(
    catalog_registry: ConnectorCatalogRegistry,
) -> None:
    use_case = GetAppSpecUseCase(registry=catalog_registry)
    with pytest.raises(ConnectorNotFoundException, match="Unknown connector 'unknown_app'"):
        await use_case.execute(GetAppSpecQuery(app_id="unknown_app"))


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
    spec = registry.get_app_spec("custom_crm")
    assert spec.display_name == "Custom Enterprise CRM"

    connector = registry.get_connector("custom_crm")
    assert connector.app_id == "custom_crm"

    registry.unregister("custom_crm")
    assert len(registry.list_apps()) == 0
    with pytest.raises(ConnectorNotFoundException):
        registry.get_connector("custom_crm")
