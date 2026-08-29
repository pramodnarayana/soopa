from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.adapters.outbound.database.postgres_job_repository import PostgresJobRepository
from scheduler.adapters.outbound.database.uow import SqlAlchemySchedulerUnitOfWork


@pytest.mark.asyncio
async def test_sqlalchemy_scheduler_uow():
    session = AsyncMock(spec=AsyncSession)

    uow = SqlAlchemySchedulerUnitOfWork(session=session)

    assert isinstance(uow.job_repo, PostgresJobRepository)

    async with uow:
        assert uow.session == session

    # Verify commit
    await uow.commit()
    session.commit.assert_awaited_once()

    # Verify rollback
    await uow.rollback()
    session.rollback.assert_awaited_once()
