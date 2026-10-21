"""HTTP request and response DTOs for the Integration Platform connector catalog."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CatalogAppSummaryHttpResponse(BaseModel):
    """HTTP response for a single connector catalog application summary."""

    app_id: str = Field(..., description="Unique connector identifier")
    display_name: str = Field(..., description="Human-readable application name")
    category: str = Field(..., description="Application category, e.g. CRM, BILLING, ENERGY")
    auth_type: str = Field(
        ..., description="Authentication protocol: OAUTH2, BEARER, API_KEY, BASIC"
    )
    description: str | None = Field(None, description="Brief summary of application capabilities")
    connector_type: str = Field("DECLARATIVE_HTTP", description="Connector runtime architecture")
    icon_url: str | None = Field(None, description="Static icon asset URL")


class AppSpecHttpResponse(BaseModel):
    """HTTP response containing dynamic UI form schema for connector configuration."""

    app_id: str = Field(..., description="Unique connector identifier")
    display_name: str = Field(..., description="Human-readable application name")
    auth_type: str = Field(..., description="Authentication protocol")
    category: str = Field(..., description="Application category")
    properties: list[dict[str, Any]] = Field(..., description="Dynamic form property schemas")
    description: str | None = Field(None, description="Connector description")
