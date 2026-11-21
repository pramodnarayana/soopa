"""Inbound HTTP router for Universal Multi-Stage Replay and Audit Ledger."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_data_plane_uow_provider,
    get_payload_storage,
    require_flows_write,
    require_tenant_member,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)
from ip.engine.adapters.inbound.api.dtos.universal_replay_dtos import (
    UniversalExecuteReplayHttpRequest,
    UniversalReplayExecutionHttpResponse,
    UniversalReplayPreviewHttpRequest,
    UniversalReplayPreviewHttpResponse,
)
from ip.engine.application.replay.ip_replay_service import IpReplayApplicationService
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort
from replay.domain.dtos import ExecuteReplayCommandDTO, ReplayPreviewRequestDTO
from replay.domain.enums import ReplayStage, ReplayTargetType
from storage.ports.payload_storage_port import PayloadStoragePort

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/replay",
    tags=["Integration Platform - Universal Replay"],
)


@router.post(
    "/preview",
    response_model=UniversalReplayPreviewHttpResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
    },
)
async def preview_replay(
    tenant_id: str,
    body: UniversalReplayPreviewHttpRequest,
    _context: Annotated[IdentityContext, Depends(require_tenant_member)],
    dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    payload_storage: Annotated[PayloadStoragePort, Depends(get_payload_storage)],
) -> UniversalReplayPreviewHttpResponse | Response:
    """Evaluates the side-effects and boundaries of a proposed multi-stage replay."""
    logger.info(
        "ip_universal_replay_preview.received",
        tenant_id=tenant_id,
        target_id=body.target_id,
        target_type=body.target_type,
        target_stage=body.target_stage,
    )

    try:
        stage = ReplayStage(body.target_stage)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid replay stage: {body.target_stage}",
        )

    try:
        target_type = ReplayTargetType(body.target_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid replay target type: {body.target_type}",
        )

    shard_res = await dp_uow_provider.resolve_shard_info(tenant_id)
    if shard_res.is_err:
        return from_ip_error(shard_res.unwrap_err())
    shard_id, shard_dsn = shard_res.unwrap()

    async with dp_uow_provider.get_data_plane_uow(tenant_id, shard_id, shard_dsn) as uow:
        service = IpReplayApplicationService(
            storage=payload_storage,
            manifest_repo=uow.batch_manifests,
            ledger_repo=uow.replay_ledger,
        )
        req_dto = ReplayPreviewRequestDTO(
            target_id=body.target_id,
            tenant_id=tenant_id,
            target_stage=stage,
            target_type=target_type,
            modified_payload=body.modified_payload,
        )
        res = await service.preview_replay(req_dto)

    if res.is_err:
        err_msg = str(res.error) if res.error is not None else "Replay preview failed"
        logger.error("ip_universal_replay_preview.failed", error=err_msg)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        )

    preview_dto = res.unwrap()
    return UniversalReplayPreviewHttpResponse(
        target_id=preview_dto.target_id,
        target_type=preview_dto.target_type.value,
        target_stage=preview_dto.target_stage.value,
        affected_entity_count=preview_dto.affected_entity_count,
        total_record_count=preview_dto.total_record_count,
        window_start_utc=preview_dto.window_start_utc,
        window_end_utc=preview_dto.window_end_utc,
        estimated_duration_seconds=preview_dto.estimated_duration_seconds,
        will_deliver_to_egress=preview_dto.will_deliver_to_egress,
        requires_idempotency_key=preview_dto.requires_idempotency_key,
    )


@router.post(
    "/execute",
    response_model=UniversalReplayExecutionHttpResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
    },
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_replay(
    tenant_id: str,
    body: UniversalExecuteReplayHttpRequest,
    context: Annotated[IdentityContext, Depends(require_flows_write)],
    dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    payload_storage: Annotated[PayloadStoragePort, Depends(get_payload_storage)],
) -> UniversalReplayExecutionHttpResponse | Response:
    """Initiates a multi-stage replay and persists an audit ledger record."""
    actor = context.subject or "UNKNOWN_OPERATOR"
    logger.info(
        "ip_universal_replay_execute.received",
        tenant_id=tenant_id,
        target_id=body.target_id,
        target_type=body.target_type,
        target_stage=body.target_stage,
        actor=actor,
        idempotency_key=body.idempotency_key,
    )

    try:
        stage = ReplayStage(body.target_stage)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid replay stage: {body.target_stage}",
        )

    try:
        target_type = ReplayTargetType(body.target_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid replay target type: {body.target_type}",
        )

    shard_res = await dp_uow_provider.resolve_shard_info(tenant_id)
    if shard_res.is_err:
        return from_ip_error(shard_res.unwrap_err())
    shard_id, shard_dsn = shard_res.unwrap()

    async with dp_uow_provider.get_data_plane_uow(tenant_id, shard_id, shard_dsn) as uow:
        service = IpReplayApplicationService(
            storage=payload_storage,
            manifest_repo=uow.batch_manifests,
            ledger_repo=uow.replay_ledger,
        )
        cmd_dto = ExecuteReplayCommandDTO(
            target_id=body.target_id,
            tenant_id=tenant_id,
            target_stage=stage,
            actor=actor,
            reason=body.reason,
            idempotency_key=body.idempotency_key,
            target_type=target_type,
            payload_override=body.payload_override,
            original_trace_id=body.original_trace_id,
            correlation_id=body.correlation_id,
        )
        res = await service.execute_replay(cmd_dto)
        await uow.commit()

    if res.is_err:
        err_msg = str(res.error) if res.error is not None else "Replay execution failed"
        logger.error("ip_universal_replay_execute.failed", error=err_msg)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        )

    exec_dto = res.unwrap()
    return UniversalReplayExecutionHttpResponse(
        replay_id=exec_dto.replay_id,
        target_id=exec_dto.target_id,
        target_type=exec_dto.target_type.value,
        trace_id=exec_dto.trace_id,
        target_stage=exec_dto.target_stage.value,
        status=exec_dto.status.value,
        initiated_at_utc=exec_dto.initiated_at_utc,
    )
