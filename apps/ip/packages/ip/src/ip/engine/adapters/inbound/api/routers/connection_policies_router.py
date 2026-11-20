"""FastAPI router for managing Connection Operational Policies (ip.connection_policies)."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_control_plane_uow,
    require_flows_read,
    require_flows_write,
)
from ip.engine.adapters.inbound.api.dtos.connection_policy_dtos import (
    ConnectionPolicyHttpResponse,
    UpsertConnectionPolicyHttpRequest,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)
from ip.engine.application.use_cases.connections.connection_policy_use_cases import (
    ConnectionPolicyDTO,
    DeleteConnectionPolicyCommand,
    DeleteConnectionPolicyUseCase,
    GetConnectionPolicyQuery,
    GetConnectionPolicyUseCase,
    UpsertConnectionPolicyCommand,
    UpsertConnectionPolicyUseCase,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/policy",
    tags=["IP - Connection Policies"],
)


def _to_response_dto(dto: ConnectionPolicyDTO) -> ConnectionPolicyHttpResponse:
    return ConnectionPolicyHttpResponse(
        id=dto.id,
        tenant_id=dto.tenant_id,
        connection_id=dto.connection_id,
        max_query_window_days=dto.max_query_window_days,
        max_query_window_hours=dto.max_query_window_hours,
        min_query_window_minutes=dto.min_query_window_minutes,
        max_entities_per_call=dto.max_entities_per_call,
        max_records_per_batch=dto.max_records_per_batch,
        max_concurrency=dto.max_concurrency,
        rate_limit_rpm=dto.rate_limit_rpm,
        cooldown_seconds_between_calls=dto.cooldown_seconds_between_calls,
        supports_wildcard_queries=dto.supports_wildcard_queries,
        blackout_cron_schedule=dto.blackout_cron_schedule,
        blackout_duration_minutes=dto.blackout_duration_minutes,
        vendor_quirks=dto.vendor_quirks,
        is_enabled=dto.is_enabled,
        created_at=dto.created_at,
        updated_at=dto.updated_at,
    )


@router.get(
    "",
    response_model=ConnectionPolicyHttpResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ApiErrorHttpResponse, "description": "Connection or policy not found"},
    },
)
async def get_connection_policy(
    tenant_id: str,
    connection_id: str,
    _identity: Annotated[IdentityContext, Depends(require_flows_read)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> ConnectionPolicyHttpResponse | JSONResponse:
    """Retrieves operational policy configuration for a specific Connection."""
    logger.info(
        "http_get_connection_policy.received",
        tenant_id=tenant_id,
        connection_id=connection_id,
    )
    use_case = GetConnectionPolicyUseCase(control_plane_uow=uow)
    result = await use_case.execute(
        GetConnectionPolicyQuery(tenant_id=tenant_id, connection_id=connection_id)
    )
    if result.is_err:
        return from_ip_error(result.unwrap_err())
    return _to_response_dto(result.unwrap())


@router.put(
    "",
    response_model=ConnectionPolicyHttpResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ApiErrorHttpResponse, "description": "Connection not found"},
    },
)
async def upsert_connection_policy(
    tenant_id: str,
    connection_id: str,
    body: UpsertConnectionPolicyHttpRequest,
    _identity: Annotated[IdentityContext, Depends(require_flows_write)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> ConnectionPolicyHttpResponse | JSONResponse:
    """Configures or updates operational policies for a Connection."""
    logger.info(
        "http_upsert_connection_policy.received",
        tenant_id=tenant_id,
        connection_id=connection_id,
    )
    use_case = UpsertConnectionPolicyUseCase(control_plane_uow=uow)
    command = UpsertConnectionPolicyCommand(
        tenant_id=tenant_id,
        connection_id=connection_id,
        policy_id=body.policy_id,
        max_query_window_days=body.max_query_window_days,
        max_query_window_hours=body.max_query_window_hours,
        min_query_window_minutes=body.min_query_window_minutes,
        max_entities_per_call=body.max_entities_per_call,
        max_records_per_batch=body.max_records_per_batch,
        max_concurrency=body.max_concurrency,
        rate_limit_rpm=body.rate_limit_rpm,
        cooldown_seconds_between_calls=body.cooldown_seconds_between_calls,
        supports_wildcard_queries=body.supports_wildcard_queries,
        blackout_cron_schedule=body.blackout_cron_schedule,
        blackout_duration_minutes=body.blackout_duration_minutes,
        vendor_quirks=body.vendor_quirks,
        is_enabled=body.is_enabled,
    )
    result = await use_case.execute(command)
    if result.is_err:
        return from_ip_error(result.unwrap_err())
    return _to_response_dto(result.unwrap())


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": ApiErrorHttpResponse, "description": "Connection or policy not found"},
    },
)
async def delete_connection_policy(
    tenant_id: str,
    connection_id: str,
    _identity: Annotated[IdentityContext, Depends(require_flows_write)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> Response:
    """Deletes operational policy configuration for a Connection."""
    logger.info(
        "http_delete_connection_policy.received",
        tenant_id=tenant_id,
        connection_id=connection_id,
    )
    use_case = DeleteConnectionPolicyUseCase(control_plane_uow=uow)
    result = await use_case.execute(
        DeleteConnectionPolicyCommand(tenant_id=tenant_id, connection_id=connection_id)
    )
    if result.is_err:
        return from_ip_error(result.unwrap_err())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
