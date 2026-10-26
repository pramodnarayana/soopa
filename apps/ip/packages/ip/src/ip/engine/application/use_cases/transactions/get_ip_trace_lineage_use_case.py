"""Use case for retrieving the execution attempt lineage tree and correlation-key traces."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

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


class GetIpTraceLineageUseCase:
    """Retrieves the chronological replay lineage tree and supports business correlation key lookup."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._uow_provider = uow_provider

    async def execute(
        self, query: GetIpTraceLineageQuery
    ) -> Result[list[IpTraceLineageItemDTO], IpError]:
        shard_res = await self._uow_provider.resolve_shard_info(query.tenant_id)
        if shard_res.is_err:
            return Result.err(shard_res.unwrap_err())

        shard_id, shard_dsn = shard_res.unwrap()
        async with self._uow_provider.get_data_plane_uow(
            query.tenant_id, shard_id, shard_dsn
        ) as uow:
            lineage = await uow.traces.get_trace_lineage(query.tenant_id, query.trace_id)
            return Result.ok(lineage)

    async def search_by_correlation_id(
        self, query: SearchTracesByCorrelationQuery
    ) -> Result[list[IpTraceLineageItemDTO], IpError]:
        shard_res = await self._uow_provider.resolve_shard_info(query.tenant_id)
        if shard_res.is_err:
            return Result.err(shard_res.unwrap_err())

        shard_id, shard_dsn = shard_res.unwrap()
        async with self._uow_provider.get_data_plane_uow(
            query.tenant_id, shard_id, shard_dsn
        ) as uow:
            items = await uow.traces.find_traces_by_correlation_id(
                query.tenant_id,
                query.correlation_id,
                limit=query.limit,
            )
            return Result.ok(items)


__all__ = [
    "GetIpTraceLineageQuery",
    "GetIpTraceLineageUseCase",
    "SearchTracesByCorrelationQuery",
]
