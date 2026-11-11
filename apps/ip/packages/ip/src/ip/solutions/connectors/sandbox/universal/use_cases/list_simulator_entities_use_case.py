"""Use case to list all Simulator Entities configured for a Simulator Connection."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.solutions.connectors.sandbox.universal.dto import SimulatorEntityDTO
from ip.solutions.connectors.sandbox.universal.ports import SimulatorUnitOfWorkPort
from ip.solutions.connectors.sandbox.universal.use_cases.connection_guard import (
    verify_simulator_connection,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ListSimulatorEntitiesQuery:
    """Query to retrieve all Simulator Entities inside `(tenant_id, connection_id)`."""

    tenant_id: str
    connection_id: str


class ListSimulatorEntitiesUseCase:
    """Lists all `SimulatorEntityDTO` rows inside a tenant-owned Simulator Connection."""

    def __init__(
        self,
        *,
        uow: SimulatorUnitOfWorkPort,
        connections: ConnectionRepositoryPort,
    ) -> None:
        self._uow = uow
        self._connections = connections

    async def execute(
        self, query: ListSimulatorEntitiesQuery
    ) -> Result[Sequence[SimulatorEntityDTO], IpError]:
        tenant_id = query.tenant_id.strip()
        connection_id = query.connection_id.strip()
        async with self._uow:
            conn_res = await verify_simulator_connection(
                self._connections,
                tenant_id=tenant_id,
                connection_id=connection_id,
            )
            if conn_res.is_err:
                err = conn_res.unwrap_err()
                logger.error(
                    "simulator_entity_list_connection_invalid",
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    error_code=err.code.value,
                )
                return Result.fail(err)
            entities = await self._uow.entities.list_entities_by_connection(
                tenant_id, connection_id
            )
        return Result.ok(entities)


__all__ = ["ListSimulatorEntitiesQuery", "ListSimulatorEntitiesUseCase"]
