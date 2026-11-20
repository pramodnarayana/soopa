"""Use case for listing recent durable Stitch WorkflowRuns on a tenant shard."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from orchestration.domain.constants import RunStatus

from ip.engine.application.use_cases.stitch.dtos import StitchRunSummaryDTO, to_run_dto
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.ports.outbound.stitch_catalog_registry_port import StitchShardGatewayPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ListStitchRunsQuery:
    """Query to list recent durable Stitch WorkflowRuns on a tenant shard."""

    tenant_id: str
    workflow_id: str | None = None
    status: RunStatus | None = None
    limit: int = 50


class ListStitchRunsUseCase:
    """Lists recent durable Stitch WorkflowRuns and their StepRun states on the tenant Data Plane shard."""

    def __init__(self, *, shard_gateway: StitchShardGatewayPort) -> None:
        self._shard_gateway = shard_gateway

    async def execute(
        self, query: ListStitchRunsQuery
    ) -> Result[tuple[StitchRunSummaryDTO, ...], IpError]:
        bound = logger.bind(
            tenant_id=query.tenant_id,
            workflow_id=query.workflow_id,
            status=query.status.value if query.status is not None else None,
            limit=query.limit,
        )
        bound.info("list_stitch_runs.received")
        res = await self._shard_gateway.list_runs(
            tenant_id=query.tenant_id,
            workflow_id=query.workflow_id,
            status=query.status,
            limit=query.limit,
        )
        if res.is_err:
            err = res.unwrap_err()
            bound.error(
                "list_stitch_runs.failed",
                error_code=err.code.value,
                error=err.message,
            )
            return Result.err(err)
        runs = res.unwrap()
        dtos = tuple(to_run_dto(r) for r in runs)
        bound.info("list_stitch_runs.completed", count=len(dtos))
        return Result.ok(dtos)


__all__ = [
    "ListStitchRunsQuery",
    "ListStitchRunsUseCase",
]
