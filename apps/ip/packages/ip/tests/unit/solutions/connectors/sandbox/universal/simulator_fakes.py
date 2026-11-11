"""Shared pure in-memory test fakes for Simulator Entity unit tests."""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType

from ip.engine.domain.exceptions import IpError, Result
from ip.solutions.connectors.sandbox.universal.dto import SimulatorEntityDTO
from ip.solutions.connectors.sandbox.universal.ports import (
    DuplicateSimulatorEntityError,
    SimulatorRepositoryPort,
    SimulatorUnitOfWorkPort,
)


class InMemorySimulatorRepository(SimulatorRepositoryPort):
    """Deterministic in-memory implementation of `SimulatorRepositoryPort` (zero DB dependency)."""

    def __init__(self) -> None:
        self._entities: dict[str, SimulatorEntityDTO] = {}

    async def list_entities_by_connection(
        self, tenant_id: str, connection_id: str
    ) -> Sequence[SimulatorEntityDTO]:
        matched = [
            e
            for e in self._entities.values()
            if e.tenant_id == tenant_id and e.connection_id == connection_id
        ]
        matched.sort(key=lambda e: (e.created_at, e.id))
        return tuple(matched)

    async def get_entity_by_name(
        self, tenant_id: str, connection_id: str, entity_name: str
    ) -> SimulatorEntityDTO | None:
        for ent in self._entities.values():
            if (
                ent.tenant_id == tenant_id
                and ent.connection_id == connection_id
                and ent.entity_name == entity_name
            ):
                return ent
        return None

    async def get_entity_by_id(
        self, tenant_id: str, connection_id: str, entity_id: str
    ) -> SimulatorEntityDTO | None:
        ent = self._entities.get(entity_id)
        if ent is not None and ent.tenant_id == tenant_id and ent.connection_id == connection_id:
            return ent
        return None

    async def count_entities_by_connection(self, tenant_id: str, connection_id: str) -> int:
        return sum(
            1
            for ent in self._entities.values()
            if ent.tenant_id == tenant_id and ent.connection_id == connection_id
        )

    async def create_entity(
        self, entity: SimulatorEntityDTO
    ) -> Result[SimulatorEntityDTO, IpError]:
        if (
            await self.get_entity_by_name(
                entity.tenant_id, entity.connection_id, entity.entity_name
            )
            is not None
        ):
            return Result.fail(
                DuplicateSimulatorEntityError.for_name(entity.connection_id, entity.entity_name)
            )
        self._entities[entity.id] = entity
        return Result.ok(entity)

    async def update_entity(
        self, entity: SimulatorEntityDTO
    ) -> Result[SimulatorEntityDTO, IpError]:
        for ent_id, existing in self._entities.items():
            if (
                ent_id != entity.id
                and existing.tenant_id == entity.tenant_id
                and existing.connection_id == entity.connection_id
                and existing.entity_name == entity.entity_name
            ):
                return Result.fail(
                    DuplicateSimulatorEntityError.for_name(entity.connection_id, entity.entity_name)
                )
        self._entities[entity.id] = entity
        return Result.ok(entity)

    async def delete_entity(self, tenant_id: str, connection_id: str, entity_id: str) -> bool:
        ent = self._entities.get(entity_id)
        if ent is None or ent.tenant_id != tenant_id or ent.connection_id != connection_id:
            return False
        del self._entities[entity_id]
        return True


class FakeSimulatorUnitOfWork(SimulatorUnitOfWorkPort):
    """In-memory `SimulatorUnitOfWorkPort` recording atomic `commit` and `rollback` counts."""

    entities: InMemorySimulatorRepository

    def __init__(self, repository: InMemorySimulatorRepository | None = None) -> None:
        self.entities = repository or InMemorySimulatorRepository()
        self.commits: int = 0
        self.rollbacks: int = 0

    async def __aenter__(self) -> FakeSimulatorUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


__all__ = ["FakeSimulatorUnitOfWork", "InMemorySimulatorRepository"]
