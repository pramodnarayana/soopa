"""Use case to fetch a specific tenant connection by ID."""

from __future__ import annotations

from dataclasses import dataclass

from ip.engine.application.dto import ConnectionDTO, ConnectionOperationResultDTO
from ip.engine.domain.exceptions import ConnectionNotFoundError
from ip.engine.ports.outbound.uow import ControlPlaneUnitOfWorkPort


@dataclass(frozen=True)
class GetConnectionQuery:
    """Query parameters for fetching a specific connection."""

    tenant_id: str
    connection_id: str


class GetConnectionUseCase:
    """Fetches a tenant-scoped connection and returns a structured result DTO inside a Control Plane UoW."""

    def __init__(self, uow: ControlPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, query: GetConnectionQuery) -> ConnectionOperationResultDTO:
        async with self._uow:
            conn = await self._uow.connections.get_by_id(query.connection_id)
            if not conn or conn.tenant_id != query.tenant_id:
                return ConnectionOperationResultDTO.from_error(
                    ConnectionNotFoundError.for_id(query.connection_id)
                )
            return ConnectionOperationResultDTO.ok(ConnectionDTO.from_domain(conn))
