"""Inbound HTTP router for Integration Platform connector catalog."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query, Response, status
from ip.engine.application.use_cases.catalog.get_app_spec_use_case import (
    GetAppSpecQuery,
    GetAppSpecUseCase,
)
from ip.engine.application.use_cases.catalog.list_catalog_apps_use_case import (
    ListCatalogAppsQuery,
    ListCatalogAppsUseCase,
)
from ip.engine.domain.exceptions import ConnectorNotFoundError
from ip.engine.ports.outbound.catalog_registry_port import CatalogRegistryPort

from unified_api.adapters.inbound.http.dependencies.ip.services import get_catalog_registry
from unified_api.adapters.inbound.http.ip.dtos.catalog_dtos import (
    AppSpecHttpResponse,
    CatalogAppSummaryHttpResponse,
    ConnectorPropertyHttpResponse,
    DropdownOptionHttpResponse,
    OAuthConfigHttpResponse,
)
from unified_api.adapters.inbound.http.ip.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/ip/catalog",
    tags=["Integration Platform - Catalog"],
)


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
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
    status_code=status.HTTP_200_OK,
)
async def get_catalog_app_spec(
    app_id: str,
    registry: CatalogRegistryPort = Depends(get_catalog_registry),
) -> AppSpecHttpResponse | Response:
    """Retrieves dynamic property schema and UI specification for an application."""
    use_case = GetAppSpecUseCase(registry=registry)
    result = await use_case.execute(GetAppSpecQuery(app_id=app_id))
    if not result.success or result.spec is None:
        return from_ip_error(result.error or ConnectorNotFoundError.for_app(app_id))

    spec = result.spec
    properties = [
        ConnectorPropertyHttpResponse(
            name=p.name,
            label=p.label,
            type=p.type,
            required=p.required,
            default=p.default,
            description=p.description,
            options=[
                DropdownOptionHttpResponse(label=opt.label, value=opt.value) for opt in p.options
            ],
            oauth_config=(
                OAuthConfigHttpResponse(
                    auth_url=p.oauth_config.auth_url,
                    token_url=p.oauth_config.token_url,
                    scopes=list(p.oauth_config.scopes),
                    client_id=p.oauth_config.client_id,
                )
                if p.oauth_config is not None
                else None
            ),
        )
        for p in spec.properties
    ]
    return AppSpecHttpResponse(
        app_id=spec.app_id,
        display_name=spec.display_name,
        auth_type=spec.auth_type,
        category=spec.category,
        properties=properties,
        description=spec.description,
    )
