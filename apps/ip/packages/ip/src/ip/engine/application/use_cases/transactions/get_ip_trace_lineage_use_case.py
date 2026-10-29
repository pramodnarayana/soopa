"""Use case for retrieving the execution attempt lineage tree and correlation-key traces."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from strace.domain import TraceStatus

from ip.engine.application.dtos.trace import IpTraceLineageItemDTO
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class GetIpTraceLineageQuery:
    """Query to fetch the ordered replay attempt history for a transaction trace."""

    tenant_id: str
    trace_id: str


@dataclass(frozen=True, kw_only=True)
class SearchTracesByCorrelationQuery:
    """Query to search traces by business correlation key (e.g. meter_id, order_id, invoice_no)."""

    tenant_id: str
    correlation_id: str
    limit: int = 50


@dataclass(frozen=True, kw_only=True)
class ListRecentTracesQuery:
    """Query to list recent trace lineage summaries for the Support Timeline feed."""

    tenant_id: str
    status: TraceStatus | None = None
    min_replay_count: int | None = None
    limit: int = 50


class GetIpTraceLineageUseCase:
    """Retrieves the chronological replay lineage tree and supports business correlation key lookup."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._uow_provider = uow_provider

    async def execute(
        self, query: GetIpTraceLineageQuery
    ) -> Result[list[IpTraceLineageItemDTO], IpError]:
        bound = logger.bind(tenant_id=query.tenant_id, trace_id=query.trace_id)
        bound.info("ip_trace_lineage.execute_started")
        shard_res = await self._uow_provider.resolve_shard_info(query.tenant_id)
        if shard_res.is_err:
            err = shard_res.unwrap_err()
            bound.error(
                "ip_trace_lineage.shard_resolution_failed",
                error_code=str(err.code),
                message=err.message,
            )
            return Result.err(err)

        shard_id, shard_dsn = shard_res.unwrap()
        async with self._uow_provider.get_data_plane_uow(
            query.tenant_id, shard_id, shard_dsn
        ) as uow:
            lineage = await uow.traces.get_trace_lineage(query.tenant_id, query.trace_id)
        bound.info(
            "ip_trace_lineage.execute_completed",
            shard_id=shard_id,
            attempt_count=len(lineage),
        )
        return Result.ok(lineage)

    async def search_by_correlation_id(
        self, query: SearchTracesByCorrelationQuery
    ) -> Result[list[IpTraceLineageItemDTO], IpError]:
        bound = logger.bind(
            tenant_id=query.tenant_id,
            correlation_id=query.correlation_id,
            limit=query.limit,
        )
        bound.info("ip_trace_lineage.search_started")
        shard_res = await self._uow_provider.resolve_shard_info(query.tenant_id)
        if shard_res.is_err:
            err = shard_res.unwrap_err()
            bound.error(
                "ip_trace_lineage.shard_resolution_failed",
                error_code=str(err.code),
                message=err.message,
            )
            return Result.err(err)

        shard_id, shard_dsn = shard_res.unwrap()
        async with self._uow_provider.get_data_plane_uow(
            query.tenant_id, shard_id, shard_dsn
        ) as uow:
            items = await uow.traces.find_traces_by_correlation_id(
                query.tenant_id,
                query.correlation_id,
                limit=query.limit,
            )
        bound.info(
            "ip_trace_lineage.search_completed",
            shard_id=shard_id,
            result_count=len(items),
        )
        return Result.ok(items)

    async def list_recent(
        self, query: ListRecentTracesQuery
    ) -> Result[list[IpTraceLineageItemDTO], IpError]:
        bound = logger.bind(
            tenant_id=query.tenant_id,
            status_filter=query.status.value if query.status is not None else None,
            min_replay_count=query.min_replay_count,
            limit=query.limit,
        )
        bound.info("ip_trace_lineage.list_recent_started")
        shard_res = await self._uow_provider.resolve_shard_info(query.tenant_id)
        if shard_res.is_err:
            err = shard_res.unwrap_err()
            bound.error(
                "ip_trace_lineage.shard_resolution_failed",
                error_code=str(err.code),
                message=err.message,
            )
            return Result.err(err)

        shard_id, shard_dsn = shard_res.unwrap()
        async with self._uow_provider.get_data_plane_uow(
            query.tenant_id, shard_id, shard_dsn
        ) as uow:
            result = await uow.traces.list_recent_traces(
                query.tenant_id,
                status=query.status,
                min_replay_count=query.min_replay_count,
                limit=query.limit,
            )

        bound.info(
            "ip_trace_lineage.list_recent_completed",
            shard_id=shard_id,
            returned_count=len(result),
        )
        return Result.ok(result)


__all__ = [
    "GetIpTraceLineageQuery",
    "GetIpTraceLineageUseCase",
    "ListRecentTracesQuery",
    "SearchTracesByCorrelationQuery",
]
