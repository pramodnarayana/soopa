"""Inbound HTTP router for Integration Platform Stage Replay."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Response, status
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_data_plane_uow_provider,
    get_ip_stage_replay_processors,
    require_tenant_member,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)
from ip.engine.adapters.inbound.api.dtos.replay_dtos import (
    BulkReplayHttpRequest,
    BulkReplayHttpResponse,
    ModifyAndReplayHttpRequest,
    ReplayStageHttpRequest,
    ReplayStageHttpResponse,
    map_bulk_replay_result_to_http,
    map_replay_result_to_http,
)
from ip.engine.application.use_cases.replay.bulk_replay_stage_use_case import (
    BulkReplayStageCommand,
    BulkReplayStageUseCase,
)
from ip.engine.application.use_cases.replay.modify_and_replay_use_case import (
    ModifyAndReplayCommand,
    ModifyAndReplayUseCase,
)
from ip.engine.application.use_cases.replay.replay_stage_use_case import (
    ReplayStageCommand,
    ReplayStageUseCase,
)
from ip.engine.application.use_cases.replay.stage_replay_processor import StageReplayProcessorPort
from ip.engine.domain.enums import PipelineStage
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/traces",
    tags=["Integration Platform - Stage Replay"],
)


@router.post(
    "/bulk-replay",
    response_model=BulkReplayHttpResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
    status_code=status.HTTP_202_ACCEPTED,
)
async def bulk_replay_stages(
    tenant_id: str,
    request: BulkReplayHttpRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    stage_processors: Annotated[
        Mapping[PipelineStage, StageReplayProcessorPort],
        Depends(get_ip_stage_replay_processors),
    ],
) -> BulkReplayHttpResponse | Response:
    """Bulk-replays up to 100 traces from the requested pipeline stage."""
    actor = context.subject or "USER"
    log = logger.bind(
        tenant_id=tenant_id,
        stage=request.stage.value,
        requested_count=len(request.trace_ids),
        actor=actor,
    )
    log.info("ip_bulk_replay_stages.received")

    use_case = BulkReplayStageUseCase(
        uow_provider=uow_provider,
        stage_processors=stage_processors,
    )
    result = await use_case.execute(
        BulkReplayStageCommand(
            tenant_id=tenant_id,
            trace_ids=tuple(request.trace_ids),
            stage=request.stage,
            actor=actor,
        )
    )
    if result.is_err:
        err = result.unwrap_err()
        log.error("ip_bulk_replay_stages.failed", error_code=err.code.value)
        return from_ip_error(err)

    dto = result.unwrap()
    log.info(
        "ip_bulk_replay_stages.accepted",
        replayed_count=dto.replayed_count,
        failed_count=len(dto.failed_items),
    )
    return map_bulk_replay_result_to_http(dto)


@router.post(
    "/{trace_id}/replay",
    response_model=ReplayStageHttpResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
    },
    status_code=status.HTTP_202_ACCEPTED,
)
async def replay_stage(
    tenant_id: str,
    trace_id: str,
    request: ReplayStageHttpRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    stage_processors: Annotated[
        Mapping[PipelineStage, StageReplayProcessorPort],
        Depends(get_ip_stage_replay_processors),
    ],
) -> ReplayStageHttpResponse | Response:
    """Deterministically replays an Integration Platform trace from Ingest, Normalize, Stitch, or Deliver."""
    actor = context.subject or "USER"
    log = logger.bind(
        tenant_id=tenant_id,
        trace_id=trace_id,
        stage=request.stage.value,
        actor=actor,
    )
    log.info("ip_replay_stage.received")

    use_case = ReplayStageUseCase(
        uow_provider=uow_provider,
        stage_processors=stage_processors,
    )
    result = await use_case.execute(
        ReplayStageCommand(
            tenant_id=tenant_id,
            trace_id=trace_id,
            stage=request.stage,
            actor=actor,
        )
    )
    if result.is_err:
        err = result.unwrap_err()
        log.error("ip_replay_stage.failed", error_code=err.code.value, reason=err.message)
        return from_ip_error(err, trace_id=trace_id)

    dto = result.unwrap()
    log.info(
        "ip_replay_stage.accepted",
        new_trace_id=dto.new_trace_id,
        replay_count=dto.replay_count,
    )
    return map_replay_result_to_http(dto)


@router.post(
    "/{trace_id}/modify-and-replay",
    response_model=ReplayStageHttpResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
    },
    status_code=status.HTTP_202_ACCEPTED,
)
async def modify_and_replay_stage(
    tenant_id: str,
    trace_id: str,
    request: ModifyAndReplayHttpRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    stage_processors: Annotated[
        Mapping[PipelineStage, StageReplayProcessorPort],
        Depends(get_ip_stage_replay_processors),
    ],
) -> ReplayStageHttpResponse | Response:
    """Overrides an Ingest or Stitch payload and triggers a new immutable replay trace."""
    actor = context.subject or "USER"
    log = logger.bind(
        tenant_id=tenant_id,
        trace_id=trace_id,
        stage=request.stage.value,
        actor=actor,
    )
    log.info("ip_modify_and_replay_stage.received")

    use_case = ModifyAndReplayUseCase(
        uow_provider=uow_provider,
        stage_processors=stage_processors,
    )
    result = await use_case.execute(
        ModifyAndReplayCommand(
            tenant_id=tenant_id,
            trace_id=trace_id,
            stage=request.stage,
            modified_payload=request.modified_payload,
            actor=actor,
        )
    )
    if result.is_err:
        err = result.unwrap_err()
        log.error(
            "ip_modify_and_replay_stage.failed",
            error_code=err.code.value,
            reason=err.message,
        )
        return from_ip_error(err, trace_id=trace_id)

    dto = result.unwrap()
    log.info(
        "ip_modify_and_replay_stage.accepted",
        new_trace_id=dto.new_trace_id,
        replay_count=dto.replay_count,
    )
    return map_replay_result_to_http(dto)
