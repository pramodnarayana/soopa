"""Use case to test connectivity and validate credentials against external applications."""

from collections.abc import Mapping
from dataclasses import dataclass

import structlog
from ip.application.responses import ConnectionCheckResultDTO
from ip.domain.types import JsonDict
from ip.ports.outbound.connector_port import ConnectorPort

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

    def __init__(self, connectors: Mapping[str, ConnectorPort]) -> None:
        self._connectors = connectors

    async def execute(self, command: CheckConnectionCommand) -> ConnectionCheckResultDTO:
        connector = self._connectors.get(command.app_id)
        if not connector:
            logger.error(
                "connection_check_connector_not_found",
                app_id=command.app_id,
            )
            return ConnectionCheckResultDTO(
                success=False,
                status="FAILED",
                message=f"Connector '{command.app_id}' is not registered.",
                error_code="CONNECTOR_NOT_FOUND",
            )

        result = await connector.check(command.public_config, command.raw_credentials)
        logger.info(
            "connection_checked",
            app_id=command.app_id,
            auth_type=command.auth_type,
            check_success=result.success,
            check_status=result.status,
        )
        return result
