"""HTTP request and response DTOs for the Integration Platform connector catalog."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DropdownOptionHttpResponse(BaseModel):
    """HTTP response for a single dropdown option item."""

    label: str = Field(..., description="Human-readable label for dropdown option")
    value: str = Field(..., description="Underlying value submitted for option")


class OAuthConfigHttpResponse(BaseModel):
    """HTTP response for OAuth2 authorization parameters."""

    auth_url: str = Field(..., description="OAuth authorization endpoint URL")
    token_url: str = Field(..., description="OAuth token exchange endpoint URL")
    scopes: list[str] = Field(default_factory=list, description="Requested OAuth scopes")
    client_id: str | None = Field(None, description="Public OAuth client ID")


class ConnectorPropertyHttpResponse(BaseModel):
    """HTTP response for a single connector configuration parameter schema."""

    name: str = Field(..., description="Property identifier key")
    label: str = Field(..., description="Form input label")
    type: str = Field(
        ..., description="Field type, e.g. shortText, secretText, number, boolean, dropdown, oauth"
    )
    required: bool = Field(True, description="Whether this property is required")
    default: str | int | float | bool | None = Field(None, description="Default value")
    description: str | None = Field(None, description="Help text or tooltip")
    options: list[DropdownOptionHttpResponse] = Field(
        default_factory=list, description="Dropdown options"
    )
    oauth_config: OAuthConfigHttpResponse | None = Field(
        None, description="OAuth parameters if type is oauth"
    )


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
    properties: list[ConnectorPropertyHttpResponse] = Field(
        default_factory=list, description="Dynamic form property schemas"
    )
    description: str | None = Field(None, description="Connector description")
