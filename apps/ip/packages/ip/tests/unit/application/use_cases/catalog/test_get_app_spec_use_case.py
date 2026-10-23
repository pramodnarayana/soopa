"""Unit tests for GetAppSpecUseCase."""

from __future__ import annotations

import pytest
from ip.application.connectors.registry_loader import create_default_catalog_registry
from ip.engine.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.engine.application.use_cases.catalog.get_app_spec_use_case import (
    GetAppSpecQuery,
    GetAppSpecUseCase,
)
from ip.engine.domain.exceptions import ConnectorNotFoundError, IpErrorCode


@pytest.fixture
def catalog_registry() -> ConnectorCatalogRegistry:
    return create_default_catalog_registry()


@pytest.mark.asyncio
async def test_get_app_spec_use_case(catalog_registry: ConnectorCatalogRegistry) -> None:
    use_case = GetAppSpecUseCase(registry=catalog_registry)
    result = await use_case.execute(GetAppSpecQuery(app_id="salesforce"))
    assert result.success is True
    assert result.spec is not None
    assert result.spec.app_id == "salesforce"
    assert result.spec.display_name == "Salesforce CRM"
    assert len(result.spec.properties) > 0


@pytest.mark.asyncio
async def test_get_app_spec_use_case_not_found(
    catalog_registry: ConnectorCatalogRegistry,
) -> None:
    use_case = GetAppSpecUseCase(registry=catalog_registry)
    result = await use_case.execute(GetAppSpecQuery(app_id="unknown_app"))
    assert result.success is False
    assert result.spec is None
    assert isinstance(result.error, ConnectorNotFoundError)
    assert result.error_code == IpErrorCode.CONNECTOR_NOT_FOUND.value
    assert "not found" in str(result.error_message)
