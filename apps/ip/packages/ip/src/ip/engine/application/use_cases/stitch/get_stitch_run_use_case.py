"""Use case for inspecting a Stitch WorkflowRun on a tenant shard."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from ip.engine.application.use_cases.stitch.dtos import StitchRunSummaryDTO, to_run_dto
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.ports.outbound.stitch_catalog_registry_port import StitchShardGatewayPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class GetStitchRunQuery:
    """Query to inspect a Stitch WorkflowRun on a tenant shard."""

    tenant_id: str
    run_id: str


class GetStitchRunUseCase:
    """Inspects a durable Stitch WorkflowRun and its StepRun states on the tenant Data Plane shard."""

    def __init__(self, *, shard_gateway: StitchShardGatewayPort) -> None:
        self._shard_gateway = shard_gateway

    async def execute(self, query: GetStitchRunQuery) -> Result[StitchRunSummaryDTO, IpError]:
        bound = logger.bind(tenant_id=query.tenant_id, run_id=query.run_id)
        bound.info("get_stitch_run.received")
        res = await self._shard_gateway.get_run(
            tenant_id=query.tenant_id,
            run_id=query.run_id,
        )
        if res.is_err:
            err = res.unwrap_err()
            bound.error(
                "get_stitch_run.failed",
                error_code=err.code.value,
                error=err.message,
            )
            return Result.err(err)
        run = res.unwrap()
        bound.info("get_stitch_run.completed", status=run.status.value)
        return Result.ok(to_run_dto(run))


__all__ = [
    "GetStitchRunQuery",
    "GetStitchRunUseCase",
]
