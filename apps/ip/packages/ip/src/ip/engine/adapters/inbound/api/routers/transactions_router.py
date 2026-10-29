"""Inbound HTTP router for Integration Platform Transactions, Trace Waterfall, Lineage, and Replay."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, Response, status
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_data_plane_uow_provider,
    require_tenant_member,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)
from ip.engine.adapters.inbound.api.dtos.transaction_dtos import (
    BulkReplayHttpRequest,
    BulkReplayHttpResponse,
    IpTraceHttpResponse,
    IpTraceLineageItemHttpResponse,
    ModifyAndReplayHttpRequest,
    ReplayTransactionHttpRequest,
    ReplayTransactionHttpResponse,
    map_bulk_replay_result_to_http,
    map_ip_trace_dto_to_http,
    map_lineage_item_to_http,
    map_replay_result_to_http,
)
from ip.engine.application.use_cases.transactions.bulk_replay_transactions_use_case import (
    BulkReplayCommand,
    BulkReplayTransactionsUseCase,
)
from ip.engine.application.use_cases.transactions.get_ip_trace_lineage_use_case import (
    GetIpTraceLineageQuery,
    GetIpTraceLineageUseCase,
    ListRecentTracesQuery,
    SearchTracesByCorrelationQuery,
)
from ip.engine.application.use_cases.transactions.get_ip_trace_use_case import (
    GetIpTraceQuery,
    GetIpTraceUseCase,
)
from ip.engine.application.use_cases.transactions.modify_and_replay_use_case import (
    ModifyAndReplayCommand,
    ModifyAndReplayTransactionUseCase,
)
from ip.engine.application.use_cases.transactions.replay_transaction_use_case import (
    ReplayTransactionCommand,
    ReplayTransactionUseCase,
)
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort
from strace.domain import TraceStatus

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/transactions",
    tags=["Integration Platform - Transactions & Replay"],
)


@router.get(
    "",
    response_model=list[IpTraceLineageItemHttpResponse],
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
    status_code=status.HTTP_200_OK,
)
async def list_recent_traces(
    tenant_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    status_filter: Annotated[
        TraceStatus | None,
        Query(alias="status", description="Optional TraceStatus filter (e.g. FAILED, DELIVERED)"),
    ] = None,
    min_replay_count: Annotated[
        int | None,
        Query(
            ge=1,
            description="Optional minimum replay_count filter (e.g. 1 for replayed traces)",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[IpTraceLineageItemHttpResponse] | Response:
    """Lists recent transaction trace summaries for the tenant Support Timeline."""
    _ = context
    log = logger.bind(
        tenant_id=tenant_id,
        status_filter=status_filter.value if status_filter is not None else None,
        min_replay_count=min_replay_count,
        limit=limit,
    )
    log.info("ip_list_recent_traces.received")

    use_case = GetIpTraceLineageUseCase(uow_provider=uow_provider)
    result = await use_case.list_recent(
        ListRecentTracesQuery(
            tenant_id=tenant_id,
            status=status_filter,
            min_replay_count=min_replay_count,
            limit=limit,
        )
    )
    if result.is_err:
        err = result.unwrap_err()
        log.error("ip_list_recent_traces.failed", error_code=err.code.value)
        return from_ip_error(err)

    items = result.unwrap()
    log.info("ip_list_recent_traces.completed", count=len(items))
    return [map_lineage_item_to_http(item) for item in items]


@router.get(
    "/search",
    response_model=list[IpTraceLineageItemHttpResponse],
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
    status_code=status.HTTP_200_OK,
)
async def search_traces_by_correlation_id(
    tenant_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    correlation_id: str = Query(
        ...,
        min_length=1,
        description="Business correlation key (e.g. meter_id, order_id, invoice_no)",
    ),
    limit: int = Query(50, ge=1, le=200),
) -> list[IpTraceLineageItemHttpResponse] | Response:
    """Searches transaction traces across L1, L2, L3, and L5 by business correlation ID."""
    log = logger.bind(tenant_id=tenant_id, correlation_id=correlation_id, limit=limit)
    log.info("ip_search_traces_by_correlation.received")

    use_case = GetIpTraceLineageUseCase(uow_provider=uow_provider)
    result = await use_case.search_by_correlation_id(
        SearchTracesByCorrelationQuery(
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            limit=limit,
        )
    )
    if result.is_err:
        err = result.unwrap_err()
        log.error("ip_search_traces_by_correlation.failed", error_code=err.code.value)
        return from_ip_error(err)

    items = result.unwrap()
    log.info("ip_search_traces_by_correlation.completed", match_count=len(items))
    return [map_lineage_item_to_http(item) for item in items]


@router.post(
    "/bulk-replay",
    response_model=BulkReplayHttpResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
    status_code=status.HTTP_202_ACCEPTED,
)
async def bulk_replay_transactions(
    tenant_id: str,
    request: BulkReplayHttpRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
) -> BulkReplayHttpResponse | Response:
    """Bulk-replays up to 100 Integration Platform transactions from the requested stage."""
    actor = context.subject or "USER"
    log = logger.bind(
        tenant_id=tenant_id,
        stage=request.stage.value,
        requested_count=len(request.trace_ids),
        actor=actor,
    )
    log.info("ip_bulk_replay_transactions.received")

    use_case = BulkReplayTransactionsUseCase(uow_provider=uow_provider)
    result = await use_case.execute(
        BulkReplayCommand(
            tenant_id=tenant_id,
            trace_ids=tuple(request.trace_ids),
            stage=request.stage,
            actor=actor,
        )
    )
    if result.is_err:
        err = result.unwrap_err()
        log.error("ip_bulk_replay_transactions.failed", error_code=err.code.value)
        return from_ip_error(err)

    dto = result.unwrap()
    log.info(
        "ip_bulk_replay_transactions.accepted",
        replayed_count=dto.replayed_count,
        failed_count=len(dto.failed_items),
    )
    return map_bulk_replay_result_to_http(dto)


@router.get(
    "/{trace_id}",
    response_model=IpTraceHttpResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
    status_code=status.HTTP_200_OK,
)
async def get_ip_trace(
    tenant_id: str,
    trace_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    hydrate_payloads: bool = Query(
        True,
        description="Hydrate offloaded S3 request/response bodies and upstream parent stages",
    ),
) -> IpTraceHttpResponse | Response:
    """Fetches the end-to-end 5-layer waterfall snapshot of an Integration Platform trace."""
    log = logger.bind(tenant_id=tenant_id, trace_id=trace_id, hydrate_payloads=hydrate_payloads)
    log.info("ip_get_trace.received")

    use_case = GetIpTraceUseCase(uow_provider=uow_provider)
    result = await use_case.execute(
        GetIpTraceQuery(
            tenant_id=tenant_id,
            trace_id=trace_id,
            hydrate_payloads=hydrate_payloads,
        )
    )
    if result.is_err:
        err = result.unwrap_err()
        log.error("ip_get_trace.not_found", error_code=err.code.value, reason=err.message)
        return from_ip_error(err, trace_id=trace_id)

    dto = result.unwrap()
    log.info(
        "ip_get_trace.completed",
        status=dto.status.value,
        has_inbound=dto.inbound_record is not None,
        replica_count=len(dto.replica_records),
        normalized_count=len(dto.normalized_records),
        outbound_count=len(dto.outbound_records),
    )
    return map_ip_trace_dto_to_http(dto)


@router.get(
    "/{trace_id}/lineage",
    response_model=list[IpTraceLineageItemHttpResponse],
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
    status_code=status.HTTP_200_OK,
)
async def get_ip_trace_lineage(
    tenant_id: str,
    trace_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
) -> list[IpTraceLineageItemHttpResponse] | Response:
    """Returns the chronological replay attempt lineage tree for a given trace."""
    log = logger.bind(tenant_id=tenant_id, trace_id=trace_id)
    log.info("ip_get_trace_lineage.received")

    use_case = GetIpTraceLineageUseCase(uow_provider=uow_provider)
    result = await use_case.execute(
        GetIpTraceLineageQuery(
            tenant_id=tenant_id,
            trace_id=trace_id,
        )
    )
    if result.is_err:
        err = result.unwrap_err()
        log.error("ip_get_trace_lineage.failed", error_code=err.code.value)
        return from_ip_error(err, trace_id=trace_id)

    items = result.unwrap()
    log.info("ip_get_trace_lineage.completed", attempt_count=len(items))
    return [map_lineage_item_to_http(item) for item in items]


@router.post(
    "/{trace_id}/replay",
    response_model=ReplayTransactionHttpResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
    },
    status_code=status.HTTP_202_ACCEPTED,
)
async def replay_transaction(
    tenant_id: str,
    trace_id: str,
    request: ReplayTransactionHttpRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
) -> ReplayTransactionHttpResponse | Response:
    """Deterministically replays an Integration Platform transaction from L1, L2, L3, or L5."""
    actor = context.subject or "USER"
    log = logger.bind(
        tenant_id=tenant_id,
        trace_id=trace_id,
        stage=request.stage.value,
        actor=actor,
    )
    log.info("ip_replay_transaction.received")

    use_case = ReplayTransactionUseCase(uow_provider=uow_provider)
    result = await use_case.execute(
        ReplayTransactionCommand(
            tenant_id=tenant_id,
            trace_id=trace_id,
            stage=request.stage,
            actor=actor,
        )
    )
    if result.is_err:
        err = result.unwrap_err()
        log.error("ip_replay_transaction.failed", error_code=err.code.value, reason=err.message)
        return from_ip_error(err, trace_id=trace_id)

    dto = result.unwrap()
    log.info(
        "ip_replay_transaction.accepted",
        new_trace_id=dto.new_trace_id,
        replay_count=dto.replay_count,
    )
    return map_replay_result_to_http(dto)


@router.post(
    "/{trace_id}/modify-and-replay",
    response_model=ReplayTransactionHttpResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
    },
    status_code=status.HTTP_202_ACCEPTED,
)
async def modify_and_replay_transaction(
    tenant_id: str,
    trace_id: str,
    request: ModifyAndReplayHttpRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
) -> ReplayTransactionHttpResponse | Response:
    """Overrides an L1 or L3 payload and triggers a new immutable replay trace."""
    actor = context.subject or "USER"
    log = logger.bind(
        tenant_id=tenant_id,
        trace_id=trace_id,
        stage=request.stage.value,
        actor=actor,
    )
    log.info("ip_modify_and_replay_transaction.received")

    use_case = ModifyAndReplayTransactionUseCase(uow_provider=uow_provider)
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
            "ip_modify_and_replay_transaction.failed",
            error_code=err.code.value,
            reason=err.message,
        )
        return from_ip_error(err, trace_id=trace_id)

    dto = result.unwrap()
    log.info(
        "ip_modify_and_replay_transaction.accepted",
        new_trace_id=dto.new_trace_id,
        replay_count=dto.replay_count,
    )
    return map_replay_result_to_http(dto)
