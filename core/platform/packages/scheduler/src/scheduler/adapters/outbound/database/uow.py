from database.uow import BaseSqlAlchemyUnitOfWork
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.adapters.outbound.database.postgres_job_repository import PostgresJobRepository
from scheduler.ports.outbound.uow_port import SchedulerUnitOfWorkPort


class SqlAlchemySchedulerUnitOfWork(BaseSqlAlchemyUnitOfWork, SchedulerUnitOfWorkPort):
    """
    Concrete Unit of Work adapter for the Scheduler context.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.job_repo = PostgresJobRepository(session=self.session)

    async def _pre_commit(self) -> None:
        pass
