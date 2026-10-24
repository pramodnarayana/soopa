"""Unit tests for ListCatalogAppsUseCase."""

from __future__ import annotations

import pytest
from ip.application.connectors.registry_loader import create_default_catalog_registry
from ip.engine.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.engine.application.use_cases.catalog.list_catalog_apps_use_case import (
    ListCatalogAppsQuery,
    ListCatalogAppsUseCase,
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
