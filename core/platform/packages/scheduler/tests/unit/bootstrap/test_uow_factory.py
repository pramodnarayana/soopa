import pytest
from database.provider import DatabaseProvider

from scheduler.adapters.outbound.database.uow import SqlAlchemySchedulerUnitOfWork
from scheduler.bootstrap.uow_factory import create_scheduler_uow


@pytest.mark.asyncio
async def test_create_scheduler_uow() -> None:
    provider = DatabaseProvider.from_url("sqlite+aiosqlite:///:memory:")
    async with provider.session_factory() as session:
        uow = create_scheduler_uow(session)
        assert isinstance(uow, SqlAlchemySchedulerUnitOfWork)
        assert uow.job_repo is not None
    await provider.engine.dispose()
