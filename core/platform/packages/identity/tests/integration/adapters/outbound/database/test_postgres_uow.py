import pytest

from identity.adapters.outbound.database.api_token_repository import SqlAlchemyApiTokenRepository
from identity.adapters.outbound.database.role_repository import SqlAlchemyRoleRepository
from identity.adapters.outbound.database.user_repository import SqlAlchemyUserRepository
from identity.bootstrap import create_identity_uow

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_postgres_uow_properties(db_session_factory):
    async with db_session_factory() as db_session:
        uow = create_identity_uow(db_session)
        assert isinstance(uow.role_repo, SqlAlchemyRoleRepository)
        assert isinstance(uow.user_repo, SqlAlchemyUserRepository)
        assert isinstance(uow.api_token_repo, SqlAlchemyApiTokenRepository)


@pytest.mark.asyncio
async def test_postgres_uow_commit(db_session_factory):
    async with db_session_factory() as db_session:
        uow = create_identity_uow(db_session)
        async with uow:
            # We don't actually do anything, just ensure it commits cleanly
            pass
        # commit is called automatically by __aexit__ on success


@pytest.mark.asyncio
async def test_postgres_uow_rollback(db_session_factory):
    async with db_session_factory() as db_session:
        uow = create_identity_uow(db_session)
        with pytest.raises(ValueError):
            async with uow:
                raise ValueError("Force rollback")
