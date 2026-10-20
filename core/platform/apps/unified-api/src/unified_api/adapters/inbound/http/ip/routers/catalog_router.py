"""Inbound HTTP router for Integration Platform connector catalog."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from ip.ports.outbound.catalog_registry_port import CatalogRegistryPort

from unified_api.adapters.inbound.http.ip.dtos.catalog_dtos import (
    AppSpecHttpResponse,
    CatalogAppSummaryHttpResponse,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/ip/catalog",
    tags=["Integration Platform - Catalog"],
)

_shared_registry = create_default_catalog_registry()


def get_catalog_registry() -> CatalogRegistryPort:
    return _shared_registry


@router.get(
    "/apps",
    response_model=list[CatalogAppSummaryHttpResponse],
    status_code=status.HTTP_200_OK,
)
async def list_catalog_apps(
    category: str | None = Query(
        None, description="Filter by category (CRM, BILLING, STORAGE, ENERGY, ITSM)"
    ),
    search: str | None = Query(None, description="Search query by name or appId"),
    registry: CatalogRegistryPort = Depends(get_catalog_registry),
) -> list[CatalogAppSummaryHttpResponse]:
    """Lists supported connector catalog applications with optional category and search filters."""
    use_case = ListCatalogAppsUseCase(registry=registry)
    apps = await use_case.execute(ListCatalogAppsQuery(category=category, search=search))
    return [
        CatalogAppSummaryHttpResponse(
            app_id=a.app_id,
            display_name=a.display_name,
            category=a.category,
            auth_type=a.auth_type,
            description=a.description,
            connector_type=a.connector_type,
            icon_url=a.icon_url,
        )
        for a in apps
    ]


@router.get(
    "/apps/{app_id}/spec",
    response_model=AppSpecHttpResponse,
    status_code=status.HTTP_200_OK,
)
async def get_catalog_app_spec(
    app_id: str,
    registry: CatalogRegistryPort = Depends(get_catalog_registry),
) -> AppSpecHttpResponse:
    """Retrieves dynamic property schema and UI specification for an application."""
    use_case = GetAppSpecUseCase(registry=registry)
    try:
        spec = await use_case.execute(GetAppSpecQuery(app_id=app_id))
        return AppSpecHttpResponse(
            app_id=spec.app_id,
            display_name=spec.display_name,
            auth_type=spec.auth_type,
            category=spec.category,
            properties=list(spec.properties),
            description=spec.description,
        )
    except ConnectorNotFoundException as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connector '{app_id}' not found.",
        ) from exc
