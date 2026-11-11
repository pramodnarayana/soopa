"""Shared pure in-memory test fakes for Virtual Sandbox & Entity unit tests."""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType

from ip.engine.domain.exceptions import (
    InvalidConnectionConfigError,
    InvalidCredentialsError,
    IpError,
    Result,
)
from ip.solutions.connectors.sandbox.universal.dto import (
    SimulatorEntityDTO,
    SimulatorSandboxDTO,
    verify_sandbox_api_key,
)
from ip.solutions.connectors.sandbox.universal.ports import (
    DuplicateSimulatorEntityError,
    DuplicateSimulatorSandboxError,
    SimulatorRepositoryPort,
    SimulatorUnitOfWorkPort,
)


class InMemorySimulatorRepository(SimulatorRepositoryPort):
    """Deterministic in-memory implementation of `SimulatorRepositoryPort` (zero DB dependency)."""

    def __init__(self) -> None:
        self._sandboxes: dict[str, SimulatorSandboxDTO] = {}
        self._entities: dict[str, SimulatorEntityDTO] = {}

    async def authenticate_sandbox(
        self,
        *,
        sandbox_id: str,
        raw_api_key: str,
    ) -> Result[SimulatorSandboxDTO, IpError]:
        cleaned_id = sandbox_id.strip()
        if not cleaned_id:
            return Result.fail(
                InvalidConnectionConfigError(
                    field_name="sandbox_id",
                    message="Virtual sandbox 'sandbox_id' is required in public_config.",
                    details={"field": "sandbox_id"},
                )
            )
        cleaned_key = raw_api_key.strip()
        if not cleaned_key:
            return Result.fail(
                InvalidCredentialsError(
                    message="Virtual sandbox 'api_key' credential is required.",
                    details={"sandbox_id": cleaned_id},
                )
            )
        sandbox = self._sandboxes.get(cleaned_id)
        if sandbox is None or not verify_sandbox_api_key(cleaned_key, sandbox.api_key_hash):
            return Result.fail(
                InvalidCredentialsError(
                    message="Invalid virtual sandbox ID or API key.",
                    details={"sandbox_id": cleaned_id},
                )
            )
        return Result.ok(sandbox)

    async def list_entities_by_sandbox(self, sandbox_id: str) -> Sequence[SimulatorEntityDTO]:
        matched = [e for e in self._entities.values() if e.sandbox_id == sandbox_id]
        matched.sort(key=lambda e: (e.created_at, e.id))
        return tuple(matched)

    async def get_entity_by_name(
        self, sandbox_id: str, entity_name: str
    ) -> SimulatorEntityDTO | None:
        for ent in self._entities.values():
            if ent.sandbox_id == sandbox_id and ent.entity_name == entity_name:
                return ent
        return None

    async def get_sandbox_by_id(
        self, tenant_id: str, sandbox_id: str
    ) -> SimulatorSandboxDTO | None:
        sbx = self._sandboxes.get(sandbox_id)
        if sbx is not None and sbx.tenant_id == tenant_id:
            return sbx
        return None

    async def get_sandbox_by_id_for_update(
        self, tenant_id: str, sandbox_id: str
    ) -> SimulatorSandboxDTO | None:
        return await self.get_sandbox_by_id(tenant_id, sandbox_id)

    async def list_sandboxes_by_tenant(self, tenant_id: str) -> Sequence[SimulatorSandboxDTO]:
        matched = [s for s in self._sandboxes.values() if s.tenant_id == tenant_id]
        matched.sort(key=lambda s: (s.created_at, s.id))
        return tuple(matched)

    async def create_sandbox(
        self, sandbox: SimulatorSandboxDTO
    ) -> Result[SimulatorSandboxDTO, IpError]:
        for existing in self._sandboxes.values():
            if existing.tenant_id == sandbox.tenant_id and existing.name == sandbox.name:
                return Result.fail(
                    DuplicateSimulatorSandboxError.for_name(sandbox.tenant_id, sandbox.name)
                )
        self._sandboxes[sandbox.id] = sandbox
        return Result.ok(sandbox)

    async def delete_sandbox(self, tenant_id: str, sandbox_id: str) -> bool:
        sbx = self._sandboxes.get(sandbox_id)
        if sbx is None or sbx.tenant_id != tenant_id:
            return False
        del self._sandboxes[sandbox_id]
        cascade_ids = [
            ent_id for ent_id, ent in self._entities.items() if ent.sandbox_id == sandbox_id
        ]
        for ent_id in cascade_ids:
            del self._entities[ent_id]
        return True

    async def get_entity_by_id(self, sandbox_id: str, entity_id: str) -> SimulatorEntityDTO | None:
        ent = self._entities.get(entity_id)
        if ent is not None and ent.sandbox_id == sandbox_id:
            return ent
        return None

    async def count_entities_by_sandbox(self, sandbox_id: str) -> int:
        return sum(1 for ent in self._entities.values() if ent.sandbox_id == sandbox_id)

    async def create_entity(
        self, entity: SimulatorEntityDTO
    ) -> Result[SimulatorEntityDTO, IpError]:
        if await self.get_entity_by_name(entity.sandbox_id, entity.entity_name) is not None:
            return Result.fail(
                DuplicateSimulatorEntityError.for_name(entity.sandbox_id, entity.entity_name)
            )
        self._entities[entity.id] = entity
        return Result.ok(entity)

    async def update_entity(
        self, entity: SimulatorEntityDTO
    ) -> Result[SimulatorEntityDTO, IpError]:
        for ent_id, existing in self._entities.items():
            if (
                ent_id != entity.id
                and existing.sandbox_id == entity.sandbox_id
                and existing.entity_name == entity.entity_name
            ):
                return Result.fail(
                    DuplicateSimulatorEntityError.for_name(entity.sandbox_id, entity.entity_name)
                )
        self._entities[entity.id] = entity
        return Result.ok(entity)

    async def delete_entity(self, sandbox_id: str, entity_id: str) -> bool:
        ent = self._entities.get(entity_id)
        if ent is None or ent.sandbox_id != sandbox_id:
            return False
        del self._entities[entity_id]
        return True


class FakeSimulatorUnitOfWork(SimulatorUnitOfWorkPort):
    """In-memory `SimulatorUnitOfWorkPort` recording atomic `commit` and `rollback` counts."""

    sandboxes: InMemorySimulatorRepository

    def __init__(self, repository: InMemorySimulatorRepository | None = None) -> None:
        self.sandboxes = repository or InMemorySimulatorRepository()
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
