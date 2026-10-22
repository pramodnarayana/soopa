"""Use case to list tenant connections with optional status filtering."""

from __future__ import annotations

from dataclasses import dataclass

from ip.engine.application.dto import ConnectionDTO
from ip.engine.domain.enums import ConnectionStatus
from ip.engine.ports.outbound.uow import ControlPlaneUnitOfWorkPort


@dataclass(frozen=True)
class ListConnectionsQuery:
    """Query parameters for listing tenant connections."""

    tenant_id: str
    status: ConnectionStatus | None = None


class ListConnectionsUseCase:
    """Queries and maps tenant connections into read-only boundary DTOs inside a Control Plane UoW."""

    def __init__(self, uow: ControlPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, query: ListConnectionsQuery) -> list[ConnectionDTO]:
        async with self._uow:
            connections = await self._uow.connections.list_by_tenant(
                tenant_id=query.tenant_id,
                status=query.status,
            )
            return [ConnectionDTO.from_domain(c) for c in connections]
