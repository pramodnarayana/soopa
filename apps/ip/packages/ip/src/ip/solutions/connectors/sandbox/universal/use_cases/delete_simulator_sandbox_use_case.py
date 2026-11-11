"""Use case to delete a Virtual Sandbox (cascading to its configured entities)."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from ip.engine.domain.exceptions import IpError, Result
from ip.solutions.connectors.sandbox.universal.ports import (
    SimulatorSandboxNotFoundError,
    SimulatorUnitOfWorkPort,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DeleteSimulatorSandboxCommand:
    """Command to delete a Virtual Sandbox scoped to `(tenant_id, sandbox_id)`."""

    tenant_id: str
    sandbox_id: str


class DeleteSimulatorSandboxUseCase:
    """Deletes a `SimulatorSandboxRecord` and cascades deletion to its `ip.simulator_entities` atomically."""

    def __init__(self, *, uow: SimulatorUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, command: DeleteSimulatorSandboxCommand) -> Result[bool, IpError]:
        async with self._uow:
            deleted = await self._uow.sandboxes.delete_sandbox(
                command.tenant_id.strip(),
                command.sandbox_id.strip(),
            )
            if not deleted:
                err = SimulatorSandboxNotFoundError.for_id(command.sandbox_id)
                logger.error(
                    "simulator_sandbox_delete_not_found",
                    tenant_id=command.tenant_id,
                    sandbox_id=command.sandbox_id,
                    error_code=err.code.value,
                )
                return Result.fail(err)
            await self._uow.commit()
        logger.info(
            "simulator_sandbox_deleted",
            tenant_id=command.tenant_id,
            sandbox_id=command.sandbox_id,
        )
        return Result.ok(True)


__all__ = ["DeleteSimulatorSandboxCommand", "DeleteSimulatorSandboxUseCase"]
