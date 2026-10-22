"""Use case to create and persist a new Connection aggregate."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from security.ports.cipher_port import CipherPort

from ip.engine.application.responses import ConnectionDTO, ConnectionOperationResultDTO
from ip.engine.domain.exceptions import (
    DuplicateConnectionFingerprintError,
    InvalidConnectionConfigError,
)
from ip.engine.domain.models.connection import (
    AuthType,
    Connection,
    ConnectionStatus,
    compute_connection_fingerprint,
)
from ip.engine.domain.types import JsonDict
from ip.engine.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CreateConnectionCommand:
    """Command payload to initialize a new connection."""

    tenant_id: str
    app_id: str
    name: str
    auth_type: str
    public_config: JsonDict
    raw_credentials: JsonDict
    endpoint_for_fingerprint: str | None = None


class CreateConnectionUseCase:
    """Creates a new external application connection with encrypted credentials inside a Control Plane UoW."""

    def __init__(
        self,
        uow: ControlPlaneUnitOfWorkPort,
        cipher: CipherPort,
    ) -> None:
        self._uow = uow
        self._cipher = cipher

    async def execute(self, command: CreateConnectionCommand) -> ConnectionOperationResultDTO:
        async with self._uow:
            try:
                auth_type = AuthType(command.auth_type)
            except ValueError:
                error = InvalidConnectionConfigError(
                    field_name="auth_type",
                    message=f"Unsupported authentication type '{command.auth_type}'.",
                    details={"auth_type": command.auth_type},
                )
                logger.error(
                    "connection_create_invalid_auth_type",
                    tenant_id=command.tenant_id,
                    app_id=command.app_id,
                    auth_type=command.auth_type,
                )
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(error)

            endpoint = command.endpoint_for_fingerprint or str(
                command.public_config.get("endpoint_url")
                or command.public_config.get("base_url")
                or command.public_config.get("host")
                or command.name
            )
            fingerprint = compute_connection_fingerprint(command.tenant_id, command.app_id, endpoint)

            existing = await self._uow.connections.get_by_fingerprint(
                command.tenant_id, fingerprint
            )
            if existing and existing.status != ConnectionStatus.DEACTIVATED:
                dup_error = DuplicateConnectionFingerprintError.create(
                    tenant_id=command.tenant_id,
                    app_id=command.app_id,
                    fingerprint=fingerprint,
                )
                logger.error(
                    "connection_duplicate_fingerprint_rejected",
                    tenant_id=command.tenant_id,
                    app_id=command.app_id,
                    fingerprint=fingerprint,
                    error_code=dup_error.code.value,
                )
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(dup_error)

            encrypted_creds = (
                self._cipher.encrypt(command.raw_credentials) if command.raw_credentials else None
            )

            create_result = Connection.try_create(
                tenant_id=command.tenant_id,
                app_id=command.app_id,
                name=command.name,
                auth_type=auth_type,
                public_config=command.public_config,
                encrypted_credentials=encrypted_creds,
                endpoint_for_fingerprint=endpoint,
            )
            if create_result.error is not None or create_result.value is None:
                err = create_result.error or InvalidConnectionConfigError(
                    message="Invalid connection configuration."
                )
                logger.error(
                    "connection_create_validation_failed",
                    tenant_id=command.tenant_id,
                    app_id=command.app_id,
                    error_code=err.code.value,
                    error_message=err.message,
                )
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(err)

            connection = create_result.value
            save_result = await self._uow.connections.save(connection)
            if save_result.error is not None:
                logger.error(
                    "connection_save_conflict",
                    tenant_id=command.tenant_id,
                    app_id=command.app_id,
                    fingerprint=fingerprint,
                    error_code=save_result.error.code.value,
                )
                await self._uow.rollback()
                return ConnectionOperationResultDTO.from_error(save_result.error)

            await self._uow.commit()

            logger.info(
                "connection_created",
                connection_id=connection.id,
                tenant_id=command.tenant_id,
                app_id=command.app_id,
                connection_fingerprint=fingerprint,
                auth_type=command.auth_type,
            )

            return ConnectionOperationResultDTO.ok(ConnectionDTO.from_domain(connection))
