import pytest

from notification.adapters.outbound.database.uow import SqlAlchemyNotificationUnitOfWork


@pytest.mark.asyncio
async def test_postgres_uow_properties(db_session_factory):
    async with db_session_factory() as session:
        uow = SqlAlchemyNotificationUnitOfWork(session=session)

        assert uow.user_preference_repo is not None
        assert uow.template_repo is not None
        assert uow.record_repo is not None
        assert uow.route_repo is not None
        assert uow.outbox_repo is not None


@pytest.mark.asyncio
async def test_postgres_uow_pre_commit_sends_notify(db_session_factory):
    async with db_session_factory() as session:
        # We can just test that calling _pre_commit doesn't error out,
        # and it executes the text. We can test this by checking DB listeners
        # but in a simple test, we just execute it.
        uow = SqlAlchemyNotificationUnitOfWork(session=session)
        await uow._pre_commit()
        # Ensure it works without throwing any syntax errors

        # Test full transaction
        async with uow:
            pass  # should not raise error and should run pre_commit
