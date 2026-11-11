"""Use case to retrieve a single Virtual Sandbox scoped to a tenant."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from ip.engine.domain.exceptions import IpError, Result
from ip.solutions.connectors.sandbox.universal.dto import SimulatorSandboxDTO
from ip.solutions.connectors.sandbox.universal.ports import (
    SimulatorSandboxNotFoundError,
    SimulatorUnitOfWorkPort,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class GetSimulatorSandboxQuery:
    """Query to load a specific Virtual Sandbox by `(tenant_id, sandbox_id)`."""

    tenant_id: str
    sandbox_id: str


class GetSimulatorSandboxUseCase:
    """Retrieves a `SimulatorSandboxDTO` while enforcing strict tenant isolation."""

    def __init__(self, *, uow: SimulatorUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(
        self, query: GetSimulatorSandboxQuery
    ) -> Result[SimulatorSandboxDTO, IpError]:
        async with self._uow:
            sandbox = await self._uow.sandboxes.get_sandbox_by_id(
                query.tenant_id.strip(),
                query.sandbox_id.strip(),
            )
        if sandbox is None:
            err = SimulatorSandboxNotFoundError.for_id(query.sandbox_id)
            logger.error(
                "simulator_sandbox_not_found",
                tenant_id=query.tenant_id,
                sandbox_id=query.sandbox_id,
                error_code=err.code.value,
            )
            return Result.fail(err)
        return Result.ok(sandbox)


__all__ = ["GetSimulatorSandboxQuery", "GetSimulatorSandboxUseCase"]
