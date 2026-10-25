"""Use case to test connectivity and validate credentials against external applications."""

from collections.abc import Mapping
from dataclasses import dataclass

import structlog
from seedwork.domain.types import JsonDict

from ip.engine.application.responses import ConnectionCheckResultDTO
from ip.engine.domain.exceptions import ConnectorNotFoundError
from ip.engine.ports.outbound.connector_port import ConnectorMetadataPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CheckConnectionCommand:
    """Command payload to test connectivity and credentials."""

    app_id: str
    auth_type: str
    public_config: JsonDict
    raw_credentials: JsonDict


class CheckConnectionUseCase:
    """Executes connectivity and credential health checks via the connector."""

    def __init__(self, connectors: Mapping[str, ConnectorMetadataPort]) -> None:
        self._connectors = connectors

    async def execute(self, command: CheckConnectionCommand) -> ConnectionCheckResultDTO:
        connector = self._connectors.get(command.app_id)
        if not connector:
            err = ConnectorNotFoundError(
                app_id=command.app_id,
                message=f"Connector '{command.app_id}' is not registered.",
                details={"app_id": command.app_id},
            )
            logger.error(
                "connection_check_connector_not_found",
                app_id=command.app_id,
                error_code=err.code.value,
            )
            return ConnectionCheckResultDTO.from_error(err)

        pub_config = dict(command.public_config)
        if "auth_type" not in pub_config and command.auth_type:
            pub_config["auth_type"] = command.auth_type
        result = await connector.check(pub_config, command.raw_credentials)
        logger.info(
            "connection_checked",
            app_id=command.app_id,
            auth_type=command.auth_type,
            check_success=result.success,
            check_status=result.status,
        )
        return result
