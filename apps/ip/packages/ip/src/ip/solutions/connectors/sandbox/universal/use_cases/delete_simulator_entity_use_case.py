"""Use case to delete a Simulator Entity from a Virtual Sandbox."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from ip.engine.domain.exceptions import IpError, Result
from ip.solutions.connectors.sandbox.universal.ports import (
    SimulatorEntityNotFoundError,
    SimulatorSandboxNotFoundError,
    SimulatorUnitOfWorkPort,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DeleteSimulatorEntityCommand:
    """Command to delete a Simulator Entity scoped to `(tenant_id, sandbox_id, entity_id)`."""

    tenant_id: str
    sandbox_id: str
    entity_id: str


class DeleteSimulatorEntityUseCase:
    """Deletes a `SimulatorEntityRecord` atomically after locking and verifying `sandbox_id` ownership."""

    def __init__(self, *, uow: SimulatorUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, command: DeleteSimulatorEntityCommand) -> Result[bool, IpError]:
        tenant_id = command.tenant_id.strip()
        sandbox_id = command.sandbox_id.strip()
        entity_id = command.entity_id.strip()

        async with self._uow:
            sandbox = await self._uow.sandboxes.get_sandbox_by_id_for_update(tenant_id, sandbox_id)
            if sandbox is None:
                sbx_err = SimulatorSandboxNotFoundError.for_id(command.sandbox_id)
                logger.error(
                    "simulator_entity_delete_sandbox_not_found",
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    error_code=sbx_err.code.value,
                )
                return Result.fail(sbx_err)

            deleted = await self._uow.sandboxes.delete_entity(sandbox_id, entity_id)
            if not deleted:
                not_found = SimulatorEntityNotFoundError.for_id(sandbox_id, entity_id)
                logger.error(
                    "simulator_entity_delete_not_found",
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    entity_id=entity_id,
                    error_code=not_found.code.value,
                )
                return Result.fail(not_found)

            await self._uow.commit()

        logger.info(
            "simulator_entity_deleted",
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            entity_id=entity_id,
        )
        return Result.ok(True)


__all__ = ["DeleteSimulatorEntityCommand", "DeleteSimulatorEntityUseCase"]
