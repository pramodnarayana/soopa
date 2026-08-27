from types import TracebackType
from typing import Protocol, Self

from scheduler.ports.outbound.job_repository_port import JobRepositoryPort


class SchedulerUnitOfWorkPort(Protocol):
    """
    Port defining the Unit of Work for the Scheduler bounded context.
    Encapsulates transaction boundaries and provides access to scheduler repositories.
    """

    job_repo: JobRepositoryPort

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
