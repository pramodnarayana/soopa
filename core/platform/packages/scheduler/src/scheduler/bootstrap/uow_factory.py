from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.adapters.outbound.database.sqlalchemy_job_repository import SqlAlchemyJobRepository
from scheduler.adapters.outbound.database.uow import SqlAlchemySchedulerUnitOfWork


def create_scheduler_uow(session: AsyncSession) -> SqlAlchemySchedulerUnitOfWork:
    """Composition root factory assembling SqlAlchemySchedulerUnitOfWork with concrete repositories."""
    return SqlAlchemySchedulerUnitOfWork(
        session,
        job_repo=SqlAlchemyJobRepository(session=session),
    )
