"""Use case to permanently delete a connection while preserving historical entities & data."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from ip.engine.application.responses import ConnectionDTO, ConnectionOperationResultDTO
from ip.engine.domain.exceptions import ConnectionNotFoundError
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DeleteConnectionCommand:
    """Command to permanently delete a connection while preserving entities & data."""

    connection_id: str
    tenant_id: str


class DeleteConnectionUseCase:
    """Permanently deletes connection record while keeping entities and data preserved."""

    def __init__(self, uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, command: DeleteConnectionCommand) -> ConnectionOperationResultDTO:
        async with self._uow:
            connection = await self._uow.connections.get_by_id(command.connection_id)
            if not connection or connection.tenant_id != command.tenant_id:
                not_found_err = ConnectionNotFoundError.for_id(command.connection_id)
                logger.error(
                    "connection_delete_target_not_found",
                    connection_id=command.connection_id,
                    tenant_id=command.tenant_id,
                    error_code=not_found_err.code.value,
                )
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(not_found_err)

            connection.mark_deleted()
            await self._uow.connections.delete(connection)
            await self._uow.commit()

            logger.info(
                "connection_deleted",
                connection_id=command.connection_id,
                tenant_id=command.tenant_id,
            )

            return ConnectionOperationResultDTO.ok(ConnectionDTO.from_domain(connection))
