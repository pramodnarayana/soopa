"""Universal Ingress & Webhook Endpoints API Router for Integration Platform."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Request, Response, status
from ip.engine.adapters.inbound.api.dependencies import (
    get_effective_ucp_tenant_id,
    get_ip_control_plane_uow,
    get_ip_data_plane_uow_provider,
    require_flows_read,
    require_flows_write,
    resolve_tenant_id_by_slug,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)
from ip.engine.adapters.inbound.api.dtos.webhook_dtos import (
    AddWebhookEventRouteHttpRequest,
    AddWebhookEventRouteHttpResponse,
    CreateWebhookEndpointHttpRequest,
    CreateWebhookEndpointHttpResponse,
    ReceiveWebhookPushHttpResponse,
    RotateWebhookSecretHttpResponse,
    WebhookEndpointHttpResponse,
    WebhookRouteItemHttpResponse,
)
from ip.engine.application.use_cases.ingress.add_webhook_event_route_use_case import (
    AddWebhookEventRouteCommand,
    AddWebhookEventRouteUseCase,
)
from ip.engine.application.use_cases.ingress.create_webhook_endpoint_use_case import (
    CreateWebhookEndpointCommand,
    CreateWebhookEndpointUseCase,
)
from ip.engine.application.use_cases.ingress.receive_webhook_push_use_case import (
    ReceiveWebhookPushCommand,
    ReceiveWebhookPushUseCase,
)
from ip.engine.application.use_cases.ingress.rotate_webhook_secret_use_case import (
    RotateWebhookSecretCommand,
    RotateWebhookSecretUseCase,
)
from ip.engine.domain.webhook.enums import PayloadSemantic, VerificationStrategy
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Integration Platform - Ingress Gateway & Webhook Endpoints"])


# ── Clean Public Inbound Ingress Route ─────────────────────────────────────────


@router.post(
    "/api/v1/ingress/{tenant_slug}/{endpoint_slug}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReceiveWebhookPushHttpResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ApiErrorHttpResponse},
        status.HTTP_403_FORBIDDEN: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ApiErrorHttpResponse},
    },
)
async def receive_inbound_webhook(
    tenant_slug: str,
    endpoint_slug: str,
    request: Request,
    tenant_id: Annotated[str, Depends(resolve_tenant_id_by_slug)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-ID")] = None,
) -> ReceiveWebhookPushHttpResponse | Response:
    """Universal perimeter webhook receiver.

    Evaluates 3-tier event discrimination (Headers -> Body -> Query -> Wildcard)
    and returns HTTP 202 Accepted in sub-20ms.
    """
    raw_payload = await request.body()
    headers_dict = dict(request.headers)
    query_dict = dict(request.query_params)

    use_case = ReceiveWebhookPushUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_uow_provider,
    )

    cmd = ReceiveWebhookPushCommand(
        tenant_id=tenant_id,
        endpoint_slug=endpoint_slug,
        raw_payload=raw_payload,
        headers=headers_dict,
        query_params=query_dict,
        correlation_id=correlation_id,
    )

    result = await use_case.execute(cmd)
    if result.is_err:
        err = result.unwrap_err()
        # Custom status code mapping for perimeter edge
        if err.code.value == "UNMAPPED_EVENT_ROUTE":
            return from_ip_error(err, status_code_override=status.HTTP_422_UNPROCESSABLE_CONTENT)
        if err.code.value == "WEBHOOK_VERIFICATION_FAILED":
            return from_ip_error(err, status_code_override=status.HTTP_401_UNAUTHORIZED)
        return from_ip_error(err)

    data = result.unwrap()
    return ReceiveWebhookPushHttpResponse(
        trace_id=data.trace_id,
        record_id=data.record_id,
        status=data.status,
        semantic=data.semantic,
        matched_event=data.matched_event_pattern,
        target=data.target_pipeline_or_workflow_id,
    )


# ── Webhook Endpoint Management Routes ─────────────────────────────────────────


@router.post(
    "/api/v1/endpoints",
    status_code=status.HTTP_201_CREATED,
    response_model=CreateWebhookEndpointHttpResponse,
    responses={
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
    },
    dependencies=[Depends(require_flows_write)],
)
async def create_webhook_endpoint(
    body: CreateWebhookEndpointHttpRequest,
    tenant_id: Annotated[str, Depends(get_effective_ucp_tenant_id)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> CreateWebhookEndpointHttpResponse | Response:
    """Provisions a new passive inbound WebhookEndpoint aggregate root."""
    use_case = CreateWebhookEndpointUseCase(cp_uow)
    strategy = VerificationStrategy(body.verification_strategy)

    cmd = CreateWebhookEndpointCommand(
        tenant_id=tenant_id,
        endpoint_slug=body.endpoint_slug,
        name=body.name,
        description=body.description,
        verification_strategy=strategy,
        primary_secret=body.primary_secret,
        bound_connection_id=body.bound_connection_id,
    )

    result = await use_case.execute(cmd)
    if result.is_err:
        return from_ip_error(result.unwrap_err())

    data = result.unwrap()
    return CreateWebhookEndpointHttpResponse(
        endpoint_id=data.endpoint_id,
        tenant_id=data.tenant_id,
        endpoint_slug=data.endpoint_slug,
        name=data.name,
        verification_strategy=data.verification_strategy,
        secret_token=data.secret_token,
        permanent_url=data.permanent_url_path,
        bound_connection_id=data.bound_connection_id,
    )


@router.get(
    "/api/v1/endpoints",
    response_model=list[WebhookEndpointHttpResponse],
    dependencies=[Depends(require_flows_read)],
)
async def list_webhook_endpoints(
    tenant_id: Annotated[str, Depends(get_effective_ucp_tenant_id)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> list[WebhookEndpointHttpResponse]:
    """Lists all configured webhook endpoints for the tenant."""
    async with cp_uow:
        endpoints = await cp_uow.webhook_endpoints.list_by_tenant(tenant_id)

    return [
        WebhookEndpointHttpResponse(
            id=ep.id,
            tenant_id=ep.tenant_id,
            endpoint_slug=ep.endpoint_slug,
            name=ep.name,
            description=ep.description,
            verification_strategy=ep.verification_strategy.value,
            is_active=ep.is_active,
            bound_connection_id=ep.bound_connection_id,
            created_at=ep.created_at,
            updated_at=ep.updated_at,
            routes=[
                WebhookRouteItemHttpResponse(
                    id=r.id,
                    event_pattern=r.event_pattern,
                    payload_semantic=r.payload_semantic.value,
                    target_pipeline_or_workflow_id=r.target_pipeline_or_workflow_id,
                    description=r.description,
                    priority=r.priority,
                    is_active=r.is_active,
                )
                for r in ep.event_routes
            ],
        )
        for ep in endpoints
    ]


@router.post(
    "/api/v1/endpoints/{endpoint_id}/routes",
    status_code=status.HTTP_201_CREATED,
    response_model=AddWebhookEventRouteHttpResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
    },
    dependencies=[Depends(require_flows_write)],
)
async def add_webhook_event_route(
    endpoint_id: str,
    body: AddWebhookEventRouteHttpRequest,
    tenant_id: Annotated[str, Depends(get_effective_ucp_tenant_id)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> AddWebhookEventRouteHttpResponse | Response:
    """Attaches a multiplexed event route to an existing endpoint."""
    use_case = AddWebhookEventRouteUseCase(cp_uow)
    semantic = PayloadSemantic(body.payload_semantic)

    cmd = AddWebhookEventRouteCommand(
        tenant_id=tenant_id,
        endpoint_id=endpoint_id,
        event_pattern=body.event_pattern,
        payload_semantic=semantic,
        target_pipeline_or_workflow_id=body.target_pipeline_or_workflow_id,
        description=body.description,
        priority=body.priority,
    )

    result = await use_case.execute(cmd)
    if result.is_err:
        return from_ip_error(result.unwrap_err())

    data = result.unwrap()
    return AddWebhookEventRouteHttpResponse(
        route_id=data.route_id,
        endpoint_id=data.endpoint_id,
        event_pattern=data.event_pattern,
        payload_semantic=data.payload_semantic,
        target_pipeline_or_workflow_id=data.target_pipeline_or_workflow_id,
        priority=data.priority,
    )


@router.post(
    "/api/v1/endpoints/{endpoint_id}/rotate-secret",
    status_code=status.HTTP_200_OK,
    response_model=RotateWebhookSecretHttpResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
    },
    dependencies=[Depends(require_flows_write)],
)
async def rotate_webhook_secret(
    endpoint_id: str,
    tenant_id: Annotated[str, Depends(get_effective_ucp_tenant_id)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> RotateWebhookSecretHttpResponse | Response:
    """Rotates endpoint secret, preserving previous secret as secondary fallback."""
    use_case = RotateWebhookSecretUseCase(cp_uow)
    cmd = RotateWebhookSecretCommand(tenant_id=tenant_id, endpoint_id=endpoint_id)

    result = await use_case.execute(cmd)
    if result.is_err:
        return from_ip_error(result.unwrap_err())

    data = result.unwrap()
    return RotateWebhookSecretHttpResponse(
        endpoint_id=data.endpoint_id,
        new_secret_token=data.new_secret_token,
        secret_rotated_at=data.secret_rotated_at,
    )
