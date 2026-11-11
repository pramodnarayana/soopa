"""Use case to list all Simulator Entities configured inside a Virtual Sandbox."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from ip.engine.domain.exceptions import IpError, Result
from ip.solutions.connectors.sandbox.universal.dto import SimulatorEntityDTO
from ip.solutions.connectors.sandbox.universal.ports import (
    SimulatorSandboxNotFoundError,
    SimulatorUnitOfWorkPort,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ListSimulatorEntitiesQuery:
    """Query to retrieve all Simulator Entities inside `(tenant_id, sandbox_id)`."""

    tenant_id: str
    sandbox_id: str


class ListSimulatorEntitiesUseCase:
    """Lists all `SimulatorEntityDTO` rows inside a tenant-owned Virtual Sandbox."""

    def __init__(self, *, uow: SimulatorUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(
        self, query: ListSimulatorEntitiesQuery
    ) -> Result[Sequence[SimulatorEntityDTO], IpError]:
        tenant_id = query.tenant_id.strip()
        sandbox_id = query.sandbox_id.strip()
        async with self._uow:
            sandbox = await self._uow.sandboxes.get_sandbox_by_id(tenant_id, sandbox_id)
            if sandbox is None:
                err = SimulatorSandboxNotFoundError.for_id(query.sandbox_id)
                logger.error(
                    "simulator_entity_list_sandbox_not_found",
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    error_code=err.code.value,
                )
                return Result.fail(err)
            entities = await self._uow.sandboxes.list_entities_by_sandbox(sandbox_id)
        return Result.ok(entities)


__all__ = ["ListSimulatorEntitiesQuery", "ListSimulatorEntitiesUseCase"]
