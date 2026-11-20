"""FastAPI router for managing Stitch DAG Task Runtime Configurations (ip.stitch_task_configs)."""

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
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)
from ip.engine.adapters.inbound.api.dtos.stitch_task_config_dtos import (
    StitchTaskConfigHttpResponse,
    UpsertStitchTaskConfigHttpRequest,
)
from ip.engine.application.use_cases.stitch.stitch_task_config_use_cases import (
    DeleteStitchTaskConfigCommand,
    DeleteStitchTaskConfigUseCase,
    GetStitchTaskConfigQuery,
    GetStitchTaskConfigUseCase,
    ListStitchTaskConfigsQuery,
    ListStitchTaskConfigsUseCase,
    StitchTaskConfigDTO,
    UpsertStitchTaskConfigCommand,
    UpsertStitchTaskConfigUseCase,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/stitches/{stitch_id}/task-configs",
    tags=["IP - Stitch Task Runtime Configurations"],
)


def _to_response_dto(dto: StitchTaskConfigDTO) -> StitchTaskConfigHttpResponse:
    return StitchTaskConfigHttpResponse(
        id=dto.id,
        tenant_id=dto.tenant_id,
        stitch_id=dto.stitch_id,
        node_key=dto.node_key,
        timeout_seconds=dto.timeout_seconds,
        heartbeat_interval_seconds=dto.heartbeat_interval_seconds,
        max_attempts=dto.max_attempts,
        initial_delay_seconds=dto.initial_delay_seconds,
        backoff_multiplier=dto.backoff_multiplier,
        max_delay_seconds=dto.max_delay_seconds,
        queue_name=dto.queue_name,
        max_in_flight_tasks=dto.max_in_flight_tasks,
        failure_disposition=dto.failure_disposition,
        quarantine_stream_name=dto.quarantine_stream_name,
        created_at=dto.created_at,
        updated_at=dto.updated_at,
    )


@router.get(
    "",
    response_model=list[StitchTaskConfigHttpResponse],
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ApiErrorHttpResponse, "description": "Stitch not found"},
    },
)
async def list_stitch_task_configs(
    tenant_id: str,
    stitch_id: str,
    _identity: Annotated[IdentityContext, Depends(require_flows_read)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> list[StitchTaskConfigHttpResponse] | JSONResponse:
    """Lists all task runtime execution configurations defined for a stitch."""
    logger.info(
        "http_list_stitch_task_configs.received",
        tenant_id=tenant_id,
        stitch_id=stitch_id,
    )
    use_case = ListStitchTaskConfigsUseCase(control_plane_uow=uow)
    result = await use_case.execute(
        ListStitchTaskConfigsQuery(tenant_id=tenant_id, stitch_id=stitch_id)
    )
    if result.is_err:
        return from_ip_error(result.unwrap_err())
    return [_to_response_dto(c) for c in result.unwrap()]


@router.get(
    "/{node_key}",
    response_model=StitchTaskConfigHttpResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ApiErrorHttpResponse, "description": "Stitch or config not found"},
    },
)
async def get_stitch_task_config(
    tenant_id: str,
    stitch_id: str,
    node_key: str,
    _identity: Annotated[IdentityContext, Depends(require_flows_read)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> StitchTaskConfigHttpResponse | JSONResponse:
    """Retrieves task runtime execution policy for a specific stitch DAG node."""
    logger.info(
        "http_get_stitch_task_config.received",
        tenant_id=tenant_id,
        stitch_id=stitch_id,
        node_key=node_key,
    )
    use_case = GetStitchTaskConfigUseCase(control_plane_uow=uow)
    result = await use_case.execute(
        GetStitchTaskConfigQuery(
            tenant_id=tenant_id,
            stitch_id=stitch_id,
            node_key=node_key,
        )
    )
    if result.is_err:
        return from_ip_error(result.unwrap_err())
    return _to_response_dto(result.unwrap())


@router.put(
    "/{node_key}",
    response_model=StitchTaskConfigHttpResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ApiErrorHttpResponse, "description": "Stitch not found"},
    },
)
async def upsert_stitch_task_config(
    tenant_id: str,
    stitch_id: str,
    node_key: str,
    body: UpsertStitchTaskConfigHttpRequest,
    _identity: Annotated[IdentityContext, Depends(require_flows_write)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> StitchTaskConfigHttpResponse | JSONResponse:
    """Configures or updates task runtime execution policy for a stitch DAG node."""
    logger.info(
        "http_upsert_stitch_task_config.received",
        tenant_id=tenant_id,
        stitch_id=stitch_id,
        node_key=node_key,
    )
    use_case = UpsertStitchTaskConfigUseCase(control_plane_uow=uow)
    command = UpsertStitchTaskConfigCommand(
        tenant_id=tenant_id,
        stitch_id=stitch_id,
        node_key=node_key,
        config_id=body.config_id,
        timeout_seconds=body.timeout_seconds,
        heartbeat_interval_seconds=body.heartbeat_interval_seconds,
        max_attempts=body.max_attempts,
        initial_delay_seconds=body.initial_delay_seconds,
        backoff_multiplier=body.backoff_multiplier,
        max_delay_seconds=body.max_delay_seconds,
        queue_name=body.queue_name,
        max_in_flight_tasks=body.max_in_flight_tasks,
        failure_disposition=body.failure_disposition,
        quarantine_stream_name=body.quarantine_stream_name,
    )
    result = await use_case.execute(command)
    if result.is_err:
        return from_ip_error(result.unwrap_err())
    return _to_response_dto(result.unwrap())


@router.delete(
    "/{node_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": ApiErrorHttpResponse, "description": "Stitch or config not found"},
    },
)
async def delete_stitch_task_config(
    tenant_id: str,
    stitch_id: str,
    node_key: str,
    _identity: Annotated[IdentityContext, Depends(require_flows_write)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> Response:
    """Deletes task runtime execution policy for a stitch DAG node."""
    logger.info(
        "http_delete_stitch_task_config.received",
        tenant_id=tenant_id,
        stitch_id=stitch_id,
        node_key=node_key,
    )
    use_case = DeleteStitchTaskConfigUseCase(control_plane_uow=uow)
    result = await use_case.execute(
        DeleteStitchTaskConfigCommand(
            tenant_id=tenant_id,
            stitch_id=stitch_id,
            node_key=node_key,
        )
    )
    if result.is_err:
        return from_ip_error(result.unwrap_err())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
