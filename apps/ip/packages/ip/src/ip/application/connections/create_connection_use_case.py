"""Use case to create and persist a new Connection aggregate."""

from dataclasses import dataclass

import structlog
from ip.application.responses import ConnectionDTO
from ip.domain.exceptions import DuplicateConnectionFingerprintException
from ip.domain.models.connection import (
    AuthType,
    Connection,
    ConnectionStatus,
    compute_connection_fingerprint,
)
from ip.domain.types import JsonDict
from ip.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from security.ports.cipher_port import CipherPort

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
    """Creates a new external application connection with encrypted credentials."""

    def __init__(
        self,
        connection_repo: ConnectionRepositoryPort,
        cipher: CipherPort,
    ) -> None:
        self._connection_repo = connection_repo
        self._cipher = cipher

    async def execute(self, command: CreateConnectionCommand) -> ConnectionDTO:
        endpoint = command.endpoint_for_fingerprint or str(
            command.public_config.get("base_url")
            or command.public_config.get("host")
            or command.name
        )
        fingerprint = compute_connection_fingerprint(command.tenant_id, command.app_id, endpoint)

        existing = await self._connection_repo.get_by_fingerprint(command.tenant_id, fingerprint)
        if existing and existing.status == ConnectionStatus.ACTIVE:
            raise DuplicateConnectionFingerprintException(
                f"An active connection for {command.app_id} already exists with fingerprint {fingerprint}."
            )

        encrypted_creds = (
            self._cipher.encrypt(command.raw_credentials) if command.raw_credentials else None
        )

        auth_type = AuthType(command.auth_type)
        connection = Connection.create(
            tenant_id=command.tenant_id,
            app_id=command.app_id,
            name=command.name,
            auth_type=auth_type,
            public_config=command.public_config,
            encrypted_credentials=encrypted_creds,
            endpoint_for_fingerprint=endpoint,
        )

        await self._connection_repo.save(connection)

        logger.info(
            "connection_created",
            connection_id=connection.id,
            tenant_id=command.tenant_id,
            app_id=command.app_id,
            connection_fingerprint=fingerprint,
            auth_type=command.auth_type,
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
