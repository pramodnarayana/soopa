"""Use case to soft-deactivate an active connection without dropping schemas or data."""

from dataclasses import dataclass

import structlog
from ip.application.responses import ConnectionDTO
from ip.domain.exceptions import ConnectionNotFoundException
from ip.ports.outbound.connection_repository_port import ConnectionRepositoryPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DeactivateConnectionCommand:
    """Command to soft-deactivate an active connection."""

    connection_id: str
    tenant_id: str


class DeactivateConnectionUseCase:
    """Soft-deactivates connections, stopping pollers while preserving history."""

    def __init__(self, connection_repo: ConnectionRepositoryPort) -> None:
        self._connection_repo = connection_repo

    async def execute(self, command: DeactivateConnectionCommand) -> ConnectionDTO:
        connection = await self._connection_repo.get_by_id(command.connection_id)
        if not connection or connection.tenant_id != command.tenant_id:
            logger.warning(
                "connection_deactivation_target_not_found",
                connection_id=command.connection_id,
                tenant_id=command.tenant_id,
            )
            raise ConnectionNotFoundException(command.connection_id)

        connection.deactivate()
        await self._connection_repo.save(connection)

        logger.info(
            "connection_deactivated",
            connection_id=connection.id,
            tenant_id=command.tenant_id,
            app_id=connection.app_id,
            deactivated_at=connection.deactivated_at,
        )

        return ConnectionDTO(
            id=connection.id,
            tenant_id=connection.tenant_id,
            app_id=connection.app_id,
            name=connection.name,
            auth_type=connection.auth_type.value,
            public_config=connection.public_config,
            status=connection.status.value,
            connection_fingerprint=connection.connection_fingerprint,
            token_expires_at=connection.token_expires_at,
            last_refreshed_at=connection.last_refreshed_at,
            last_error_code=connection.last_error_code,
            last_error_message=connection.last_error_message,
            created_at=connection.created_at,
            updated_at=connection.updated_at,
            deactivated_at=connection.deactivated_at,
        )
