"""Use case to soft-deactivate an active connection without dropping schemas or data."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from ip.engine.application.responses import ConnectionDTO, ConnectionOperationResultDTO
from ip.engine.domain.exceptions import ConnectionNotFoundError
from ip.engine.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DeactivateConnectionCommand:
    """Command to soft-deactivate an active connection."""

    connection_id: str
    tenant_id: str


class DeactivateConnectionUseCase:
    """Soft-deactivates connections inside a Control Plane UoW, stopping pollers while preserving history."""

    def __init__(self, uow: ControlPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, command: DeactivateConnectionCommand) -> ConnectionOperationResultDTO:
        async with self._uow:
            connection = await self._uow.connections.get_by_id(command.connection_id)
            if not connection or connection.tenant_id != command.tenant_id:
                not_found_err = ConnectionNotFoundError.for_id(command.connection_id)
                logger.error(
                    "connection_deactivation_target_not_found",
                    connection_id=command.connection_id,
                    tenant_id=command.tenant_id,
                    error_code=not_found_err.code.value,
                )
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(not_found_err)

            deact_result = connection.deactivate()
            if deact_result.error is not None:
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(deact_result.error)

            save_result = await self._uow.connections.save(connection)
            if save_result.error is not None:
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(save_result.error)

            await self._uow.commit()

            logger.info(
                "connection_deactivated",
                connection_id=connection.id,
                tenant_id=command.tenant_id,
                app_id=connection.app_id,
                deactivated_at=connection.deactivated_at,
            )

            return ConnectionOperationResultDTO.ok(ConnectionDTO.from_domain(connection))
