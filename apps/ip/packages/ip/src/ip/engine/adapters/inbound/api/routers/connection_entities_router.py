"""FastAPI router for managing subscribed ConnectionEntity resources and checkpoints."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_control_plane_uow,
    require_tenant_member,
)
from ip.engine.adapters.inbound.api.dtos.connection_entity_dtos import (
    AddConnectionEntityHttpRequest,
    ConnectionEntityFieldHttpDTO,
    ConnectionEntityHttpResponse,
    UpdateConnectionEntityHttpRequest,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)
from ip.engine.application.use_cases.connections.connection_entity_use_cases import (
    AddConnectionEntityCommand,
    AddConnectionEntityUseCase,
    ConnectionEntityFieldDTO,
    ConnectionEntitySummaryDTO,
    ListConnectionEntitiesQuery,
    ListConnectionEntitiesUseCase,
    RemoveConnectionEntityCommand,
    RemoveConnectionEntityUseCase,
    ResetConnectionEntityCheckpointCommand,
    ResetConnectionEntityCheckpointUseCase,
    UpdateConnectionEntityCommand,
    UpdateConnectionEntityUseCase,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}/entities",
    tags=["IP - Connection Entities"],
)


def _to_entity_response(dto: ConnectionEntitySummaryDTO) -> ConnectionEntityHttpResponse:
    return ConnectionEntityHttpResponse(
        entity_id=dto.entity_id,
        tenant_id=dto.tenant_id,
        connection_id=dto.connection_id,
        stream_name=dto.stream_name,
        sync_mode=dto.sync_mode.value,
        schedule=dto.schedule.value,
        sync_from=dto.sync_from.value,
        sync_from_at=dto.sync_from_at,
        is_enabled=dto.is_enabled,
        primary_key=list(dto.primary_key),
        fields=[
            ConnectionEntityFieldHttpDTO(
                name=f.name,
                data_type=f.data_type,
                nullable=f.nullable,
                description=f.description,
            )
            for f in dto.fields
        ],
        cursor_field=dto.cursor_field,
        cursor_value=dto.cursor_value,
        records_synced_count=dto.records_synced_count,
        last_synced_at=dto.last_synced_at,
        created_at=dto.created_at,
        updated_at=dto.updated_at,
    )


@router.get(
    "",
    response_model=list[ConnectionEntityHttpResponse],
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
)
async def list_connection_entities(
    tenant_id: str,
    connection_id: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> list[ConnectionEntityHttpResponse] | JSONResponse:
    """Lists all subscribed entities configured on a connection."""
    logger.info(
        "http_list_connection_entities.received",
        tenant_id=tenant_id,
        connection_id=connection_id,
    )
    use_case = ListConnectionEntitiesUseCase(control_plane_uow=cp_uow)
    res = await use_case.execute(
        ListConnectionEntitiesQuery(tenant_id=tenant_id, connection_id=connection_id)
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_list_connection_entities.failed",
            tenant_id=tenant_id,
            connection_id=connection_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    entities = res.unwrap()
    logger.info(
        "http_list_connection_entities.completed",
        tenant_id=tenant_id,
        connection_id=connection_id,
        entity_count=len(entities),
    )
    return [_to_entity_response(e) for e in entities]


@router.post(
    "",
    response_model=ConnectionEntityHttpResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
    },
)
async def add_connection_entity(
    tenant_id: str,
    connection_id: str,
    body: AddConnectionEntityHttpRequest,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> ConnectionEntityHttpResponse | JSONResponse:
    """Subscribes an entity stream on a connection."""
    logger.info(
        "http_add_connection_entity.received",
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name=body.stream_name,
    )
    use_case = AddConnectionEntityUseCase(control_plane_uow=cp_uow)
    res = await use_case.execute(
        AddConnectionEntityCommand(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name=body.stream_name,
            sync_mode=body.sync_mode,
            schedule=body.schedule,
            sync_from=body.sync_from,
            sync_from_at=body.sync_from_at,
            is_enabled=body.is_enabled,
            primary_key=tuple(body.primary_key),
            fields=tuple(
                ConnectionEntityFieldDTO(
                    name=f.name,
                    data_type=f.data_type,
                    nullable=f.nullable,
                    description=f.description,
                )
                for f in body.fields
            ),
            cursor_field=body.cursor_field,
            default_transformation_id=body.default_transformation_id,
            default_transformation_version=body.default_transformation_version,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_add_connection_entity.failed",
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name=body.stream_name,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    dto = res.unwrap()
    logger.info(
        "http_add_connection_entity.completed",
        tenant_id=tenant_id,
        connection_id=connection_id,
        entity_id=dto.entity_id,
    )
    return _to_entity_response(dto)


@router.patch(
    "/{stream_name}",
    response_model=ConnectionEntityHttpResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
    },
)
async def update_connection_entity(
    tenant_id: str,
    connection_id: str,
    stream_name: str,
    body: UpdateConnectionEntityHttpRequest,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> ConnectionEntityHttpResponse | JSONResponse:
    """Updates sync configuration policy on a subscribed connection entity."""
    logger.info(
        "http_update_connection_entity.received",
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name=stream_name,
    )
    use_case = UpdateConnectionEntityUseCase(control_plane_uow=cp_uow)
    res = await use_case.execute(
        UpdateConnectionEntityCommand(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name=stream_name,
            sync_mode=body.sync_mode,
            schedule=body.schedule,
            sync_from=body.sync_from,
            sync_from_at=body.sync_from_at,
            is_enabled=body.is_enabled,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_update_connection_entity.failed",
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name=stream_name,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    dto = res.unwrap()
    logger.info(
        "http_update_connection_entity.completed",
        tenant_id=tenant_id,
        connection_id=connection_id,
        entity_id=dto.entity_id,
    )
    return _to_entity_response(dto)


@router.delete(
    "/{stream_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
    },
)
async def remove_connection_entity(
    tenant_id: str,
    connection_id: str,
    stream_name: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> Response:
    """Unsubscribes and deletes an entity from a connection."""
    logger.info(
        "http_remove_connection_entity.received",
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name=stream_name,
    )
    use_case = RemoveConnectionEntityUseCase(control_plane_uow=cp_uow)
    res = await use_case.execute(
        RemoveConnectionEntityCommand(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name=stream_name,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_remove_connection_entity.failed",
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name=stream_name,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    logger.info(
        "http_remove_connection_entity.completed",
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name=stream_name,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{stream_name}/reset-checkpoint",
    response_model=ConnectionEntityHttpResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
    },
)
async def reset_connection_entity_checkpoint(
    tenant_id: str,
    connection_id: str,
    stream_name: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> ConnectionEntityHttpResponse | JSONResponse:
    """Resets a subscribed entity's sync checkpoint cursor while keeping the entity subscribed."""
    logger.info(
        "http_reset_connection_entity_checkpoint.received",
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name=stream_name,
    )
    use_case = ResetConnectionEntityCheckpointUseCase(control_plane_uow=cp_uow)
    res = await use_case.execute(
        ResetConnectionEntityCheckpointCommand(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name=stream_name,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_reset_connection_entity_checkpoint.failed",
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream_name=stream_name,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    dto = res.unwrap()
    logger.info(
        "http_reset_connection_entity_checkpoint.completed",
        tenant_id=tenant_id,
        connection_id=connection_id,
        entity_id=dto.entity_id,
    )
    return _to_entity_response(dto)
