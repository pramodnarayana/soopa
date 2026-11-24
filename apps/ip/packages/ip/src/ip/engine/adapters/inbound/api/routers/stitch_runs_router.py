"""FastAPI router for Layer-4 Stitch event dispatch and durable workflow runs."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_stitch_shard_gateway,
    require_tenant_member,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import from_ip_error
from ip.engine.adapters.inbound.api.dtos.stitch_dtos import (
    StitchRunHttpResponse,
    StitchStepRunHttpResponse,
    TriggerStitchEventHttpRequest,
    TriggerStitchEventHttpResponse,
)
from ip.engine.application.use_cases.stitch import (
    GetStitchRunQuery,
    GetStitchRunUseCase,
    ListStitchRunsQuery,
    ListStitchRunsUseCase,
    StitchRunSummaryDTO,
    TriggerStitchEventCommand,
    TriggerStitchEventUseCase,
)
from ip.engine.ports.outbound.stitch_catalog_registry_port import StitchShardGatewayPort
from orchestration.domain.constants import RunStatus

logger = structlog.get_logger(__name__)

router = APIRouter(
    tags=["IP - Stitch Runs & Execution"],
)


def to_run_http_response(dto: StitchRunSummaryDTO) -> StitchRunHttpResponse:
    """Maps a StitchRunSummaryDTO to StitchRunHttpResponse."""
    return StitchRunHttpResponse(
        run_id=dto.run_id,
        tenant_id=dto.tenant_id,
        workflow_id=dto.workflow_id,
        workflow_version=dto.workflow_version,
        status=dto.status,
        priority=dto.priority,
        concurrency_key=dto.concurrency_key,
        idempotency_key=dto.idempotency_key,
        trace_id=dto.trace_id,
        correlation_id=dto.correlation_id,
        failure_code=dto.failure_code,
        failure_detail=dto.failure_detail,
        created_at=dto.created_at,
        started_at=dto.started_at,
        finished_at=dto.finished_at,
        steps=[
            StitchStepRunHttpResponse(
                step_run_id=s.step_run_id,
                node_key=s.node_key,
                status=s.status,
                retry_count=s.retry_count,
                app_retry_count=s.app_retry_count,
                internal_retry_count=s.internal_retry_count,
                iteration_count=s.iteration_count,
                failure_code=s.failure_code,
                failure_detail=s.failure_detail,
                created_at=s.created_at,
                finished_at=s.finished_at,
            )
            for s in dto.steps
        ],
    )


@router.post(
    "/dispatch",
    response_model=TriggerStitchEventHttpResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def dispatch_stitch_event(
    tenant_id: str,
    body: TriggerStitchEventHttpRequest,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    shard_gateway: Annotated[StitchShardGatewayPort, Depends(get_stitch_shard_gateway)],
) -> TriggerStitchEventHttpResponse | JSONResponse:
    """Dispatches a canonical event to matching Stitches on the tenant Data Plane shard."""
    logger.info(
        "http_dispatch_stitch_event.received",
        tenant_id=tenant_id,
        canonical_event_type=body.canonical_event_type,
    )
    use_case = TriggerStitchEventUseCase(shard_gateway=shard_gateway)
    res = await use_case.execute(
        TriggerStitchEventCommand(
            tenant_id=tenant_id,
            canonical_event_type=body.canonical_event_type,
            payload=body.payload,
            event_id=body.event_id,
            trace_id=body.trace_id,
            correlation_id=body.correlation_id,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_dispatch_stitch_event.failed",
            tenant_id=tenant_id,
            canonical_event_type=body.canonical_event_type,
            error_code=err.code.value,
        )
        return from_ip_error(err)

    dto = res.unwrap()
    logger.info(
        "http_dispatch_stitch_event.completed",
        tenant_id=tenant_id,
        started_count=len(dto.started_run_ids),
        deduplicated_count=len(dto.deduplicated_run_ids),
        signalled_count=len(dto.signalled_step_ids),
    )
    return TriggerStitchEventHttpResponse(
        started_run_ids=list(dto.started_run_ids),
        deduplicated_run_ids=list(dto.deduplicated_run_ids),
        signalled_step_ids=list(dto.signalled_step_ids),
    )


@router.get("/runs", response_model=list[StitchRunHttpResponse])
async def list_stitch_runs(
    tenant_id: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    shard_gateway: Annotated[StitchShardGatewayPort, Depends(get_stitch_shard_gateway)],
    workflow_id: Annotated[str | None, Query()] = None,
    status_filter: Annotated[RunStatus | None, Query(alias="status")] = None,
    trace_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[StitchRunHttpResponse] | JSONResponse:
    """Lists recent durable Stitch WorkflowRuns on the tenant Data Plane shard."""
    logger.info(
        "http_list_stitch_runs.received",
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        status=status_filter.value if status_filter is not None else None,
        trace_id=trace_id,
        limit=limit,
    )
    use_case = ListStitchRunsUseCase(shard_gateway=shard_gateway)
    res = await use_case.execute(
        ListStitchRunsQuery(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            status=status_filter,
            trace_id=trace_id,
            limit=limit,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_list_stitch_runs.failed",
            tenant_id=tenant_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    dtos = res.unwrap()
    logger.info(
        "http_list_stitch_runs.completed",
        tenant_id=tenant_id,
        count=len(dtos),
    )
    return [to_run_http_response(d) for d in dtos]


@router.get("/runs/{run_id}", response_model=StitchRunHttpResponse)
async def get_stitch_run(
    tenant_id: str,
    run_id: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    shard_gateway: Annotated[StitchShardGatewayPort, Depends(get_stitch_shard_gateway)],
) -> StitchRunHttpResponse | JSONResponse:
    """Inspects a durable Stitch WorkflowRun and its StepRun states on the tenant Data Plane shard."""
    logger.info(
        "http_get_stitch_run.received",
        tenant_id=tenant_id,
        run_id=run_id,
    )
    use_case = GetStitchRunUseCase(shard_gateway=shard_gateway)
    res = await use_case.execute(
        GetStitchRunQuery(
            tenant_id=tenant_id,
            run_id=run_id,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_get_stitch_run.failed",
            tenant_id=tenant_id,
            run_id=run_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    dto = res.unwrap()
    logger.info(
        "http_get_stitch_run.completed",
        tenant_id=tenant_id,
        run_id=run_id,
        status=dto.status,
    )
    return to_run_http_response(dto)


__all__ = ["router", "to_run_http_response"]
