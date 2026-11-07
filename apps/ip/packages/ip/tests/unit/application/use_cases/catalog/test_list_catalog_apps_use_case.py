"""Unit tests for ListCatalogAppsUseCase."""

from __future__ import annotations

import pytest
from ip.engine.adapters.outbound.auth.resolver import AuthStrategyResolver
from ip.engine.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.engine.adapters.outbound.connectors.generic_http_connector import GenericHttpConnector
from ip.engine.application.use_cases.catalog.list_catalog_apps_use_case import (
    ListCatalogAppsQuery,
    ListCatalogAppsUseCase,
)
from ip.engine.bootstrap.container import create_engine_catalog_registry
from ip.engine.ports.outbound.catalog_registry_port import CatalogAppSummaryDTO


@pytest.fixture
def catalog_registry() -> ConnectorCatalogRegistry:
    auth_resolver = AuthStrategyResolver()
    registry = create_engine_catalog_registry(auth_resolver=auth_resolver)
    registry.register_connector(
        GenericHttpConnector(
            app_id="acme_protocol",
            auth_resolver=auth_resolver,
            allow_private_ips=False,
        ),
        CatalogAppSummaryDTO(
            app_id="acme_protocol",
            display_name="Acme Protocol Adapter",
            category="PROTOCOL",
            auth_type="BEARER_TOKEN",
            description="Synthetic protocol connector",
            connector_type="NATIVE",
        ),
    )
    return registry


@pytest.mark.asyncio
async def test_list_catalog_apps_use_case(catalog_registry: ConnectorCatalogRegistry) -> None:
    use_case = ListCatalogAppsUseCase(registry=catalog_registry)
    all_apps = await use_case.execute(ListCatalogAppsQuery(tenant_id="ten_01"))
    assert len(all_apps) >= 2

    protocol_apps = await use_case.execute(
        ListCatalogAppsQuery(tenant_id="ten_01", category="PROTOCOL")
    )
    assert len(protocol_apps) >= 1
    for app_summary in protocol_apps:
        assert app_summary.category.upper() == "PROTOCOL"

    sftp_apps = await use_case.execute(ListCatalogAppsQuery(tenant_id="ten_01", search="sftp"))
    assert len(sftp_apps) == 1
    assert sftp_apps[0].app_id == "sftp"
