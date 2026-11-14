"""HTTP Request and Response DTO schemas for Webhook Ingress Endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CreateWebhookEndpointHttpRequest(BaseModel):
    """Payload to provision a new passive inbound webhook endpoint."""

    model_config = ConfigDict(frozen=True)

    endpoint_slug: str = Field(
        ...,
        min_length=2,
        max_length=128,
        description="Clean, brandable URL slug (e.g. 'orders-hub', 'shopify').",
    )
    name: str = Field(..., min_length=2, max_length=255, description="Human-readable name.")
    description: str = Field(default="", max_length=1000)
    verification_strategy: str = Field(
        default="SHARED_HEADER_SECRET",
        description="Authentication strategy (SHARED_HEADER_SECRET, HMAC_SHA256, BEARER_TOKEN, etc.).",
    )
    primary_secret: str | None = Field(
        default=None,
        description="Optional custom secret; if omitted, the system generates a secure token.",
    )
    bound_connection_id: str | None = Field(
        default=None,
        description="Optional 1:1 binding to an outbound connection for bidirectional SaaS.",
    )


class CreateWebhookEndpointHttpResponse(BaseModel):
    """Response returned upon provisioning an endpoint, including one-time secret token."""

    model_config = ConfigDict(frozen=True)

    endpoint_id: str
    tenant_id: str
    endpoint_slug: str
    name: str
    verification_strategy: str
    secret_token: str
    permanent_url: str
    bound_connection_id: str | None = None


class AddWebhookEventRouteHttpRequest(BaseModel):
    """Payload to attach a multiplexed event route to an endpoint."""

    model_config = ConfigDict(frozen=True)

    event_pattern: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Event pattern (e.g. 'orders.created', 'historical_extract.request', '*').",
    )
    payload_semantic: str = Field(
        default="DATA",
        description="Payload semantic modality ('DATA' for L2/L3 or 'COMMAND' for L4 Orchestrator).",
    )
    target_pipeline_or_workflow_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Target pipeline ID or stitch workflow ID.",
    )
    description: str = Field(default="", max_length=500)
    priority: int = Field(default=100, ge=1, le=10000, description="Evaluation priority.")


class AddWebhookEventRouteHttpResponse(BaseModel):
    """Response containing created event route."""

    model_config = ConfigDict(frozen=True)

    route_id: str
    endpoint_id: str
    event_pattern: str
    payload_semantic: str
    target_pipeline_or_workflow_id: str
    priority: int


class WebhookRouteItemHttpResponse(BaseModel):
    """Event route summary item within an endpoint response."""

    model_config = ConfigDict(frozen=True)

    id: str
    event_pattern: str
    payload_semantic: str
    target_pipeline_or_workflow_id: str
    description: str
    priority: int
    is_active: bool


class WebhookEndpointHttpResponse(BaseModel):
    """Detailed summary of a WebhookEndpoint with its event route table."""

    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str
    endpoint_slug: str
    name: str
    description: str
    verification_strategy: str
    is_active: bool
    bound_connection_id: str | None
    created_at: str
    updated_at: str
    routes: list[WebhookRouteItemHttpResponse]


class ReceiveWebhookPushHttpResponse(BaseModel):
    """Sub-20ms acknowledgment response contract for incoming webhook pushes."""

    model_config = ConfigDict(frozen=True)

    trace_id: str
    record_id: str
    status: str = "ACCEPTED"
    semantic: str
    matched_event: str
    target: str


class RotateWebhookSecretHttpResponse(BaseModel):
    """Response returned upon successfully rotating an endpoint secret."""

    model_config = ConfigDict(frozen=True)

    endpoint_id: str
    new_secret_token: str
    secret_rotated_at: str
