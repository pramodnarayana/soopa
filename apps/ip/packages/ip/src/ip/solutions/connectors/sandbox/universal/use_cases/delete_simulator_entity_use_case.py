"""Use case to delete a Simulator Entity from a Simulator Connection."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.solutions.connectors.sandbox.universal.ports import (
    SimulatorEntityNotFoundError,
    SimulatorUnitOfWorkPort,
)
from ip.solutions.connectors.sandbox.universal.use_cases.connection_guard import (
    lock_simulator_connection,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DeleteSimulatorEntityCommand:
    """Command to delete a Simulator Entity scoped to `(tenant_id, connection_id, entity_id)`."""

    tenant_id: str
    connection_id: str
    entity_id: str


class DeleteSimulatorEntityUseCase:
    """Deletes a `SimulatorEntityRecord` atomically after locking and verifying `connection_id` ownership."""

    def __init__(
        self,
        *,
        uow: SimulatorUnitOfWorkPort,
        connections: ConnectionRepositoryPort,
    ) -> None:
        self._uow = uow
        self._connections = connections

    async def execute(self, command: DeleteSimulatorEntityCommand) -> Result[bool, IpError]:
        tenant_id = command.tenant_id.strip()
        connection_id = command.connection_id.strip()
        entity_id = command.entity_id.strip()

        async with self._uow:
            conn_res = await lock_simulator_connection(
                self._connections,
                tenant_id=tenant_id,
                connection_id=connection_id,
            )
            if conn_res.is_err:
                conn_err = conn_res.unwrap_err()
                logger.error(
                    "simulator_entity_delete_connection_invalid",
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    error_code=conn_err.code.value,
                )
                return Result.fail(conn_err)

            deleted = await self._uow.entities.delete_entity(tenant_id, connection_id, entity_id)
            if not deleted:
                not_found = SimulatorEntityNotFoundError.for_id(connection_id, entity_id)
                logger.error(
                    "simulator_entity_delete_not_found",
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    entity_id=entity_id,
                    error_code=not_found.code.value,
                )
                return Result.fail(not_found)

            await self._uow.commit()

        logger.info(
            "simulator_entity_deleted",
            tenant_id=tenant_id,
            connection_id=connection_id,
            entity_id=entity_id,
        )
        return Result.ok(True)


__all__ = ["DeleteSimulatorEntityCommand", "DeleteSimulatorEntityUseCase"]
