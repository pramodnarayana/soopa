import pytest

from identity.adapters.outbound.database.api_token_repository import PostgresApiTokenRepository
from identity.adapters.outbound.database.role_repository import PostgresRoleRepository
from identity.adapters.outbound.database.uow import SqlAlchemyIdentityUnitOfWork
from identity.adapters.outbound.database.user_repository import PostgresUserRepository

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_postgres_uow_properties(db_session_factory):
    async with db_session_factory() as db_session:
        uow = SqlAlchemyIdentityUnitOfWork(db_session)
        assert isinstance(uow.role_repo, PostgresRoleRepository)
        assert isinstance(uow.user_repo, PostgresUserRepository)
        assert isinstance(uow.api_token_repo, PostgresApiTokenRepository)


@pytest.mark.asyncio
async def test_postgres_uow_commit(db_session_factory):
    async with db_session_factory() as db_session:
        uow = SqlAlchemyIdentityUnitOfWork(db_session)
        async with uow:
            # We don't actually do anything, just ensure it commits cleanly
            pass
        # commit is called automatically by __aexit__ on success


@pytest.mark.asyncio
async def test_postgres_uow_rollback(db_session_factory):
    async with db_session_factory() as db_session:
        uow = SqlAlchemyIdentityUnitOfWork(db_session)
        with pytest.raises(ValueError):
            async with uow:
                raise ValueError("Force rollback")
