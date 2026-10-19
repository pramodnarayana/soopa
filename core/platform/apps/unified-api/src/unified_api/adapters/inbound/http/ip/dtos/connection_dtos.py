"""HTTP Request and Response DTOs for the Integration Platform connections API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateConnectionHttpRequest(BaseModel):
    """Payload to create a new external system connection."""

    app_id: str = Field(..., description="Unique application identifier (e.g. 'itron_mdm')")
    name: str = Field(..., description="User-friendly name for this connection")
    auth_type: str = Field(..., description="Authentication strategy (e.g. 'API_KEY', 'OAUTH2')")
    public_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Public configuration dictionary (endpoints, ports, timeouts)",
    )
    raw_credentials: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw credential secrets to be encrypted at rest",
    )
    endpoint_for_fingerprint: str | None = Field(
        None,
        description="Optional endpoint override used to compute the unique connection fingerprint",
    )


class CheckConnectionHttpRequest(BaseModel):
    """Payload to test external connectivity without saving a connection."""

    app_id: str
    auth_type: str
    public_config: dict[str, Any] = Field(default_factory=dict)
    raw_credentials: dict[str, Any] = Field(default_factory=dict)


class RelinkConnectionHttpRequest(BaseModel):
    """Payload to refresh credentials and reactivate a disconnected connection."""

    new_name: str | None = None
    updated_raw_credentials: dict[str, Any] = Field(default_factory=dict)


class ConnectionHttpResponse(BaseModel):
    """Safe public representation of a connection (credentials never returned)."""

    id: str
    tenant_id: str
    app_id: str
    name: str
    auth_type: str
    public_config: dict[str, Any]
    status: str
    connection_fingerprint: str
    token_expires_at: str | None = None
    last_refreshed_at: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    created_at: str
    updated_at: str
    deactivated_at: str | None = None


class ConnectionCheckHttpResponse(BaseModel):
    """Health check outcome."""

    success: bool
    status: str
    message: str | None = None
    error_code: str | None = None


class StreamFieldHttpResponse(BaseModel):
    name: str
    data_type: str
    nullable: bool = True
    description: str | None = None


class StreamSchemaHttpResponse(BaseModel):
    name: str
    fields: list[StreamFieldHttpResponse]
    primary_key: list[str]
    cursor_field: str | None = None
    supported_sync_modes: list[str]


class DiscoveredCatalogHttpResponse(BaseModel):
    """Discovered stream catalog metadata."""

    connection_id: str
    catalog_version: int
    catalog_hash: str
    streams: list[StreamSchemaHttpResponse]
    discovered_at: str
