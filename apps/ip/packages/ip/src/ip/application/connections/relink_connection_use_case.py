"""Use case to reactivate and relink a previously deactivated connection."""

from dataclasses import dataclass

import structlog
from ip.application.responses import ConnectionDTO
from ip.domain.exceptions import ConnectionNotFoundException
from ip.domain.types import JsonDict
from ip.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from security.ports.cipher_port import CipherPort

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
    """Restores deactivated connections, preserving existing catalogs and replica data."""

    def __init__(
        self,
        connection_repo: ConnectionRepositoryPort,
        cipher: CipherPort,
    ) -> None:
        self._connection_repo = connection_repo
        self._cipher = cipher

    async def execute(self, command: RelinkConnectionCommand) -> ConnectionDTO:
        connection = await self._connection_repo.get_by_id(command.connection_id)
        if not connection or connection.tenant_id != command.tenant_id:
            logger.warning(
                "connection_relink_target_not_found",
                connection_id=command.connection_id,
                tenant_id=command.tenant_id,
            )
            raise ConnectionNotFoundException(command.connection_id)

        updated_creds = (
            self._cipher.encrypt(command.updated_raw_credentials)
            if command.updated_raw_credentials is not None
            else None
        )

        connection.relink(
            new_name=command.new_name,
            updated_encrypted_credentials=updated_creds,
            updated_public_config=command.updated_public_config,
        )

        await self._connection_repo.save(connection)

        logger.info(
            "connection_relinked",
            connection_id=connection.id,
            tenant_id=command.tenant_id,
            app_id=connection.app_id,
            new_name=command.new_name,
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
