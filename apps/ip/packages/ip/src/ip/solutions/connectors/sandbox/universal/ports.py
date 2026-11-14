"""Hexagonal outbound and DI ports for Simulator Entities (`ip.simulator_entities`)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, Self, TypeVar

from ip.engine.domain.dispatch.enums import FailureDisposition
from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from ip.solutions.connectors.sandbox.universal.dto import SimulatorEntityDTO
from ip.solutions.connectors.sandbox.universal.strategies import (
    CadenceState,
    ExtractionQuery,
    PaginatedSliceDTO,
    PullExtractionMode,
    PullExtractionStrategy,
    PushCadenceMode,
    PushCadenceStrategy,
)


@dataclass(frozen=True, kw_only=True)
class DuplicateSimulatorEntityError(IpError):
    """Returned when `(tenant_id, connection_id, entity_name)` already exists in `ip.simulator_entities`."""

    connection_id: str = ""
    entity_name: str = ""
    code: IpErrorCode = IpErrorCode.VALIDATION_FAILED
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 409

    @classmethod
    def for_name(cls, connection_id: str, entity_name: str) -> DuplicateSimulatorEntityError:
        return cls(
            connection_id=connection_id,
            entity_name=entity_name,
            message=(
                f"Simulator entity '{entity_name}' already exists in connection '{connection_id}'."
            ),
            details={"connection_id": connection_id, "entity_name": entity_name},
        )


@dataclass(frozen=True, kw_only=True)
class SimulatorEntityNotFoundError(IpError):
    """Returned when a simulator entity does not exist inside the target connection."""

    connection_id: str = ""
    entity_id: str = ""
    code: IpErrorCode = IpErrorCode.STREAM_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404

    @classmethod
    def for_id(cls, connection_id: str, entity_id: str) -> SimulatorEntityNotFoundError:
        return cls(
            connection_id=connection_id,
            entity_id=entity_id,
            message=(
                f"Simulator entity '{entity_id}' was not found in connection '{connection_id}'."
            ),
            details={"connection_id": connection_id, "entity_id": entity_id},
        )


@dataclass(frozen=True, kw_only=True)
class SimulatorEntityQuotaExceededError(IpError):
    """Returned when a simulator connection reaches the per-connection entity limit."""

    connection_id: str = ""
    max_entities: int = 100
    code: IpErrorCode = IpErrorCode.VALIDATION_FAILED
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 422

    @classmethod
    def for_connection(
        cls, connection_id: str, max_entities: int
    ) -> SimulatorEntityQuotaExceededError:
        return cls(
            connection_id=connection_id,
            max_entities=max_entities,
            message=(
                f"Simulator connection '{connection_id}' reached the maximum limit of "
                f"{max_entities} entities."
            ),
            details={"connection_id": connection_id, "max_entities": max_entities},
        )


class SimulatorEntityReaderPort(Protocol):
    """Read-only port consumed by `UniversalSchemaSimulatorConnector` and `TriggerSimulatedPushUseCase`."""

    async def list_entities_by_connection(
        self, tenant_id: str, connection_id: str
    ) -> Result[Sequence[SimulatorEntityDTO], IpError]:
        """Returns all simulator entities configured for `(tenant_id, connection_id)` ordered deterministically."""
        ...

    async def get_entity_by_name(
        self, tenant_id: str, connection_id: str, entity_name: str
    ) -> Result[SimulatorEntityDTO | None, IpError]:
        """Returns a single simulator entity by `(tenant_id, connection_id, entity_name)` or `None`."""
        ...


class SimulatorRepositoryPort(SimulatorEntityReaderPort, Protocol):
    """Read-write repository port consumed by Simulator Entity CRUD use cases."""

    async def get_entity_by_id(
        self, tenant_id: str, connection_id: str, entity_id: str
    ) -> SimulatorEntityDTO | None:
        """Returns a single simulator entity scoped to `(tenant_id, connection_id, entity_id)`."""
        ...

    async def count_entities_by_connection(self, tenant_id: str, connection_id: str) -> int:
        """Returns the total number of simulator entities configured in `(tenant_id, connection_id)`."""
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

    async def delete_entity(self, tenant_id: str, connection_id: str, entity_id: str) -> bool:
        """Deletes the simulator entity row; returns `True` when deleted."""
        ...


class SimulatorUnitOfWorkPort(Protocol):
    """Transactional Unit of Work port managing atomic Simulator Entity operations."""

    entities: SimulatorRepositoryPort

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

    def get_entity_reader(self, global_session: TSession_contra) -> SimulatorEntityReaderPort:
        """Creates a request-scoped `SimulatorEntityReaderPort` bound to `global_session`."""
        ...


__all__ = [
    "CadenceState",
    "DuplicateSimulatorEntityError",
    "ExtractionQuery",
    "PaginatedSliceDTO",
    "PullExtractionMode",
    "PullExtractionStrategy",
    "PushCadenceMode",
    "PushCadenceStrategy",
    "SimulatorApiProviderPort",
    "SimulatorEntityNotFoundError",
    "SimulatorEntityQuotaExceededError",
    "SimulatorEntityReaderPort",
    "SimulatorRepositoryPort",
    "SimulatorUnitOfWorkPort",
]
