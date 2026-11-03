from database.uow import BaseSqlAlchemyUnitOfWork
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.ports.outbound.job_repository_port import JobRepositoryPort
from scheduler.ports.outbound.uow_port import SchedulerUnitOfWorkPort


class SqlAlchemySchedulerUnitOfWork(BaseSqlAlchemyUnitOfWork, SchedulerUnitOfWorkPort):
    """
    Concrete Unit of Work adapter for the Scheduler context.
    """

    def __init__(self, session: AsyncSession, *, job_repo: JobRepositoryPort) -> None:
        super().__init__(session)
        self.job_repo = job_repo

    async def _pre_commit(self) -> None:
        pass
