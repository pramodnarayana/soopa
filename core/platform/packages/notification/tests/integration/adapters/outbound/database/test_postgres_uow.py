import pytest

pytestmark = pytest.mark.integration

from notification.bootstrap.container import create_notification_uow


@pytest.mark.asyncio
async def test_sqlalchemy_uow_properties(db_session_factory):
    async with db_session_factory() as session:
        uow = create_notification_uow(session=session)

        assert uow.user_preference_repo is not None
        assert uow.template_repo is not None
        assert uow.record_repo is not None
        assert uow.route_repo is not None
        assert uow.outbox_repo is not None


@pytest.mark.asyncio
async def test_sqlalchemy_uow_pre_commit_sends_notify(db_session_factory):
    async with db_session_factory() as session:
        uow = create_notification_uow(session=session)
        await uow._pre_commit()

        async with uow:
            pass
