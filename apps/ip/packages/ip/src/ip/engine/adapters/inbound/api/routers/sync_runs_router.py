"""FastAPI router for Pull Synchronization Runs."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_effective_ucp_tenant_id,
    get_get_sync_run_use_case,
    get_list_sync_runs_use_case,
    get_trigger_sync_run_use_case,
    require_flows_read,
    require_sync_trigger,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import from_ip_error
from ip.engine.adapters.inbound.api.dtos.sync_run_dtos import (
    SyncRunHttpResponse,
    TriggerSyncRunHttpRequest,
)
from ip.engine.application.use_cases.ingestion import (
    GetSyncRunQuery,
    GetSyncRunUseCase,
    ListSyncRunsQuery,
    ListSyncRunsUseCase,
    SyncRunSummaryDTO,
    TriggerSyncRunCommand,
    TriggerSyncRunUseCase,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/connections/{connection_id}",
    tags=["IP - Sync Runs"],
)


def _to_sync_run_response(dto: SyncRunSummaryDTO) -> SyncRunHttpResponse:
    return SyncRunHttpResponse(
        run_id=dto.run_id,
        tenant_id=dto.tenant_id,
        connection_id=dto.connection_id,
        stream_name=dto.stream_name,
        kind=dto.kind,
        generation_id=dto.generation_id,
        status=dto.status,
        start_checkpoint=dto.start_checkpoint,
        end_checkpoint=dto.end_checkpoint,
        pages_count=dto.pages_count,
        records_count=dto.records_count,
        bytes_count=dto.bytes_count,
        retry_count=dto.retry_count,
        error_code=dto.error_code,
        error_message=dto.error_message,
        trace_id=dto.trace_id,
        started_at=dto.started_at,
        finished_at=dto.finished_at,
        created_at=dto.created_at,
    )


@router.post(
    "/sync-runs",
    response_model=SyncRunHttpResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_sync_run(
    connection_id: str,
    body: TriggerSyncRunHttpRequest,
    _identity: Annotated[IdentityContext, Depends(require_sync_trigger)],
    effective_tenant_id: Annotated[str, Depends(get_effective_ucp_tenant_id)],
    use_case: Annotated[TriggerSyncRunUseCase, Depends(get_trigger_sync_run_use_case)],
) -> SyncRunHttpResponse | JSONResponse:
    """Queues an asynchronous pull synchronization run via the Control Plane outbox."""
    logger.info(
        "http_trigger_sync_run.received",
        tenant_id=effective_tenant_id,
        connection_id=connection_id,
        stream_name=body.stream_name,
        forced_kind=body.forced_kind.value if body.forced_kind is not None else None,
    )
    res = await use_case.execute(
        TriggerSyncRunCommand(
            tenant_id=effective_tenant_id,
            connection_id=connection_id,
            stream_name=body.stream_name,
            forced_kind=body.forced_kind,
            correlation_id=body.correlation_id,
        )
    )
    if res.is_err:
        trigger_err = res.unwrap_err()
        logger.error(
            "http_trigger_sync_run.failed",
            tenant_id=effective_tenant_id,
            connection_id=connection_id,
            stream_name=body.stream_name,
            error_code=trigger_err.code.value,
        )
        return from_ip_error(trigger_err)
    dto = res.unwrap()
    logger.info(
        "http_trigger_sync_run.completed",
        tenant_id=effective_tenant_id,
        connection_id=connection_id,
        run_id=dto.run_id,
        trace_id=dto.trace_id,
    )
    return _to_sync_run_response(dto)


@router.get("/sync-runs", response_model=list[SyncRunHttpResponse])
async def list_sync_runs(
    connection_id: str,
    _identity: Annotated[IdentityContext, Depends(require_flows_read)],
    effective_tenant_id: Annotated[str, Depends(get_effective_ucp_tenant_id)],
    use_case: Annotated[ListSyncRunsUseCase, Depends(get_list_sync_runs_use_case)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SyncRunHttpResponse] | JSONResponse:
    """Lists recent pull synchronization runs for a connection."""
    logger.info(
        "http_list_sync_runs.received",
        tenant_id=effective_tenant_id,
        connection_id=connection_id,
        limit=limit,
    )
    res = await use_case.execute(
        ListSyncRunsQuery(
            tenant_id=effective_tenant_id,
            connection_id=connection_id,
            limit=limit,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_list_sync_runs.failed",
            tenant_id=effective_tenant_id,
            connection_id=connection_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    runs = res.unwrap()
    logger.info(
        "http_list_sync_runs.completed",
        tenant_id=effective_tenant_id,
        connection_id=connection_id,
        run_count=len(runs),
    )
    return [_to_sync_run_response(r) for r in runs]


@router.get("/sync-runs/{run_id}", response_model=SyncRunHttpResponse)
async def get_sync_run(
    connection_id: str,
    run_id: str,
    _identity: Annotated[IdentityContext, Depends(require_flows_read)],
    effective_tenant_id: Annotated[str, Depends(get_effective_ucp_tenant_id)],
    use_case: Annotated[GetSyncRunUseCase, Depends(get_get_sync_run_use_case)],
) -> SyncRunHttpResponse | JSONResponse:
    """Retrieves a specific pull synchronization run by ID."""
    logger.info(
        "http_get_sync_run.received",
        tenant_id=effective_tenant_id,
        connection_id=connection_id,
        run_id=run_id,
    )
    res = await use_case.execute(
        GetSyncRunQuery(
            tenant_id=effective_tenant_id,
            connection_id=connection_id,
            run_id=run_id,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_get_sync_run.failed",
            tenant_id=effective_tenant_id,
            connection_id=connection_id,
            run_id=run_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    run = res.unwrap()
    logger.info(
        "http_get_sync_run.completed",
        tenant_id=effective_tenant_id,
        connection_id=connection_id,
        run_id=run_id,
        status=run.status,
    )
    return _to_sync_run_response(run)
