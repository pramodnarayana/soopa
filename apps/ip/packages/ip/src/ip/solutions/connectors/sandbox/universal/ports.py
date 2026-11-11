"""Hexagonal outbound and DI ports for Virtual Sandboxes (`ip.simulator_sandboxes` & `ip.simulator_entities`)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self, TypeVar

from ip.engine.domain.dispatch.enums import FailureDisposition
from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from ip.solutions.connectors.sandbox.universal.dto import (
    SimulatorEntityDTO,
    SimulatorSandboxDTO,
)


@dataclass(frozen=True, kw_only=True)
class DuplicateSimulatorSandboxError(IpError):
    """Returned when `(tenant_id, name)` already exists in `ip.simulator_sandboxes`."""

    tenant_id: str = ""
    name: str = ""
    code: IpErrorCode = IpErrorCode.VALIDATION_FAILED
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 409

    @classmethod
    def for_name(cls, tenant_id: str, name: str) -> DuplicateSimulatorSandboxError:
        return cls(
            tenant_id=tenant_id,
            name=name,
            message=f"Virtual sandbox '{name}' already exists for tenant '{tenant_id}'.",
            details={"tenant_id": tenant_id, "name": name},
        )


@dataclass(frozen=True, kw_only=True)
class SimulatorSandboxNotFoundError(IpError):
    """Returned when a virtual sandbox does not exist for the target tenant."""

    sandbox_id: str = ""
    code: IpErrorCode = IpErrorCode.CONNECTION_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404

    @classmethod
    def for_id(cls, sandbox_id: str) -> SimulatorSandboxNotFoundError:
        return cls(
            sandbox_id=sandbox_id,
            message=f"Virtual sandbox '{sandbox_id}' was not found.",
            details={"sandbox_id": sandbox_id},
        )


@dataclass(frozen=True, kw_only=True)
class DuplicateSimulatorEntityError(IpError):
    """Returned when `(sandbox_id, entity_name)` already exists in `ip.simulator_entities`."""

    sandbox_id: str = ""
    entity_name: str = ""
    code: IpErrorCode = IpErrorCode.VALIDATION_FAILED
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 409

    @classmethod
    def for_name(cls, sandbox_id: str, entity_name: str) -> DuplicateSimulatorEntityError:
        return cls(
            sandbox_id=sandbox_id,
            entity_name=entity_name,
            message=(
                f"Simulator entity '{entity_name}' already exists in virtual sandbox '{sandbox_id}'."
            ),
            details={"sandbox_id": sandbox_id, "entity_name": entity_name},
        )


@dataclass(frozen=True, kw_only=True)
class SimulatorEntityNotFoundError(IpError):
    """Returned when a simulator entity does not exist inside the target virtual sandbox."""

    sandbox_id: str = ""
    entity_id: str = ""
    code: IpErrorCode = IpErrorCode.STREAM_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404

    @classmethod
    def for_id(cls, sandbox_id: str, entity_id: str) -> SimulatorEntityNotFoundError:
        return cls(
            sandbox_id=sandbox_id,
            entity_id=entity_id,
            message=(
                f"Simulator entity '{entity_id}' was not found in virtual sandbox '{sandbox_id}'."
            ),
            details={"sandbox_id": sandbox_id, "entity_id": entity_id},
        )


@dataclass(frozen=True, kw_only=True)
class SimulatorEntityQuotaExceededError(IpError):
    """Returned when a virtual sandbox reaches the per-sandbox entity limit."""

    sandbox_id: str = ""
    max_entities: int = 100
    code: IpErrorCode = IpErrorCode.VALIDATION_FAILED
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 422

    @classmethod
    def for_sandbox(cls, sandbox_id: str, max_entities: int) -> SimulatorEntityQuotaExceededError:
        return cls(
            sandbox_id=sandbox_id,
            max_entities=max_entities,
            message=(
                f"Virtual sandbox '{sandbox_id}' reached the maximum limit of "
                f"{max_entities} entities."
            ),
            details={"sandbox_id": sandbox_id, "max_entities": max_entities},
        )


class SimulatorSandboxReaderPort(Protocol):
    """Read-only port consumed by `UniversalSchemaSimulatorConnector` and `TriggerSimulatedPushUseCase`."""

    async def authenticate_sandbox(
        self,
        *,
        sandbox_id: str,
        raw_api_key: str,
    ) -> Result[SimulatorSandboxDTO, IpError]:
        """Authenticates `(sandbox_id, raw_api_key)` in constant time without leaking cross-tenant existence."""
        ...

    async def list_entities_by_sandbox(self, sandbox_id: str) -> Sequence[SimulatorEntityDTO]:
        """Returns all simulator entities configured inside `sandbox_id` ordered deterministically."""
        ...

    async def get_entity_by_name(
        self, sandbox_id: str, entity_name: str
    ) -> SimulatorEntityDTO | None:
        """Returns a single simulator entity by `(sandbox_id, entity_name)` or `None`."""
        ...


class SimulatorRepositoryPort(SimulatorSandboxReaderPort, Protocol):
    """Read-write repository port consumed by Virtual Sandbox and Entity CRUD use cases."""

    async def get_sandbox_by_id(
        self, tenant_id: str, sandbox_id: str
    ) -> SimulatorSandboxDTO | None:
        """Returns a virtual sandbox scoped to `(tenant_id, sandbox_id)` or `None`."""
        ...

    async def get_sandbox_by_id_for_update(
        self, tenant_id: str, sandbox_id: str
    ) -> SimulatorSandboxDTO | None:
        """Acquires a row-level lock (`SELECT ... FOR UPDATE`) on `(tenant_id, sandbox_id)` inside a UoW."""
        ...

    async def list_sandboxes_by_tenant(self, tenant_id: str) -> Sequence[SimulatorSandboxDTO]:
        """Returns all virtual sandboxes owned by `tenant_id` ordered deterministically."""
        ...

    async def create_sandbox(
        self, sandbox: SimulatorSandboxDTO
    ) -> Result[SimulatorSandboxDTO, IpError]:
        """Inserts a new virtual sandbox row, returning `DuplicateSimulatorSandboxError` on conflict."""
        ...

    async def delete_sandbox(self, tenant_id: str, sandbox_id: str) -> bool:
        """Deletes the virtual sandbox row (cascading to its entities); returns `True` when deleted."""
        ...

    async def get_entity_by_id(self, sandbox_id: str, entity_id: str) -> SimulatorEntityDTO | None:
        """Returns a single simulator entity scoped to `sandbox_id` and `entity_id`."""
        ...

    async def count_entities_by_sandbox(self, sandbox_id: str) -> int:
        """Returns the total number of simulator entities configured in `sandbox_id`."""
        ...

    async def create_entity(
        self, entity: SimulatorEntityDTO
    ) -> Result[SimulatorEntityDTO, IpError]:
        """Inserts a new simulator entity row, returning `DuplicateSimulatorEntityError` on conflict."""
        ...

    async def update_entity(
        self, entity: SimulatorEntityDTO
    ) -> Result[SimulatorEntityDTO, IpError]:
        """Updates an existing simulator entity row, returning `DuplicateSimulatorEntityError` on rename conflict."""
        ...

    async def delete_entity(self, sandbox_id: str, entity_id: str) -> bool:
        """Deletes the simulator entity row; returns `True` when deleted."""
        ...


class SimulatorUnitOfWorkPort(Protocol):
    """Transactional Unit of Work port managing atomic Virtual Sandbox & Entity operations."""

    sandboxes: SimulatorRepositoryPort

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


TSession_contra = TypeVar("TSession_contra", contravariant=True)


class SimulatorApiProviderPort(Protocol[TSession_contra]):
    """Generic DI factory port decoupling HTTP routers from concrete SQLAlchemy UoW/reader classes."""

    def create_uow(self, global_session: TSession_contra) -> SimulatorUnitOfWorkPort:
        """Creates a request-scoped `SimulatorUnitOfWorkPort` bound to `global_session`."""
        ...

    def get_sandbox_reader(self, global_session: TSession_contra) -> SimulatorSandboxReaderPort:
        """Creates a request-scoped `SimulatorSandboxReaderPort` bound to `global_session`."""
        ...


__all__ = [
    "DuplicateSimulatorEntityError",
    "DuplicateSimulatorSandboxError",
    "SimulatorApiProviderPort",
    "SimulatorEntityNotFoundError",
    "SimulatorEntityQuotaExceededError",
    "SimulatorRepositoryPort",
    "SimulatorSandboxNotFoundError",
    "SimulatorSandboxReaderPort",
    "SimulatorUnitOfWorkPort",
]
