from types import TracebackType
from typing import Protocol, TypeVar

from .outbox_repository import DataPlaneOutboxRepositoryPort
from .repository import RepositoryPort

U = TypeVar("U", bound="DataPlaneUnitOfWork")


class DataPlaneUnitOfWork(Protocol):
    """
    Unit of Work interface for the EDI Data Plane.
    Provides coordinated access to repositories within a single transaction scope.
    """

    repository: RepositoryPort
    outbox: DataPlaneOutboxRepositoryPort

    async def __aenter__(self: U) -> U: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
