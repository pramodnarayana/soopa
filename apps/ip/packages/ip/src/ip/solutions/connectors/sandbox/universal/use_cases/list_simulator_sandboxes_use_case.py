"""Use case to list all Virtual Sandboxes owned by a tenant."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ip.solutions.connectors.sandbox.universal.dto import SimulatorSandboxDTO
from ip.solutions.connectors.sandbox.universal.ports import SimulatorUnitOfWorkPort


@dataclass(frozen=True)
class ListSimulatorSandboxesQuery:
    """Query to retrieve all Virtual Sandboxes for a tenant."""

    tenant_id: str


class ListSimulatorSandboxesUseCase:
    """Lists all `SimulatorSandboxDTO` environments belonging to `tenant_id`."""

    def __init__(self, *, uow: SimulatorUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, query: ListSimulatorSandboxesQuery) -> Sequence[SimulatorSandboxDTO]:
        async with self._uow:
            return await self._uow.sandboxes.list_sandboxes_by_tenant(query.tenant_id.strip())


__all__ = ["ListSimulatorSandboxesQuery", "ListSimulatorSandboxesUseCase"]
