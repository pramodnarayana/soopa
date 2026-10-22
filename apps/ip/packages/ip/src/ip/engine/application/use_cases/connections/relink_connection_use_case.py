"""Use case to reactivate and relink a previously deactivated connection."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from security.ports.cipher_port import CipherPort
from seedwork.domain.types import JsonDict

from ip.engine.application.responses import ConnectionDTO, ConnectionOperationResultDTO
from ip.engine.domain.exceptions import ConnectionNotFoundError
from ip.engine.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RelinkConnectionCommand:
    """Command to reactivate and relink a deactivated connection."""

    connection_id: str
    tenant_id: str
    new_name: str | None = None
    updated_raw_credentials: JsonDict | None = None
    updated_public_config: JsonDict | None = None


class RelinkConnectionUseCase:
    """Restores deactivated connections inside a Control Plane UoW, preserving existing catalogs and replica data."""

    def __init__(
        self,
        uow: ControlPlaneUnitOfWorkPort,
        cipher: CipherPort,
    ) -> None:
        self._uow = uow
        self._cipher = cipher

    async def execute(self, command: RelinkConnectionCommand) -> ConnectionOperationResultDTO:
        async with self._uow:
            connection = await self._uow.connections.get_by_id(command.connection_id)
            if not connection or connection.tenant_id != command.tenant_id:
                not_found_err = ConnectionNotFoundError.for_id(command.connection_id)
                logger.error(
                    "connection_relink_target_not_found",
                    connection_id=command.connection_id,
                    tenant_id=command.tenant_id,
                    error_code=not_found_err.code.value,
                )
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(not_found_err)

            updated_creds = (
                self._cipher.encrypt(command.updated_raw_credentials)
                if command.updated_raw_credentials is not None
                else None
            )

            relink_result = connection.relink(
                new_name=command.new_name,
                updated_encrypted_credentials=updated_creds,
                updated_public_config=command.updated_public_config,
            )
            if relink_result.error is not None:
                logger.error(
                    "connection_relink_invalid_state",
                    connection_id=connection.id,
                    tenant_id=command.tenant_id,
                    current_status=connection.status.value,
                    error_code=relink_result.error.code.value,
                )
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(relink_result.error)

            save_result = await self._uow.connections.save(connection)
            if save_result.error is not None:
                logger.error(
                    "connection_relink_save_conflict",
                    connection_id=connection.id,
                    tenant_id=command.tenant_id,
                    error_code=save_result.error.code.value,
                )
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(save_result.error)

            await self._uow.commit()

            logger.info(
                "connection_relinked",
                connection_id=connection.id,
                tenant_id=command.tenant_id,
                app_id=connection.app_id,
                new_name=command.new_name,
            )

            return ConnectionOperationResultDTO.ok(ConnectionDTO.from_domain(connection))
