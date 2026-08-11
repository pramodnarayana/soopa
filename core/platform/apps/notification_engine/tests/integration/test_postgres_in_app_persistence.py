import pytest
from platform_orm.models.notifications import InAppNotification
from sqlalchemy import select

from notification_engine.adapters.outbound.postgres_in_app_persistence import (
    PostgresInAppPersistence,
)


@pytest.mark.asyncio
async def test_save_notification_persists_to_database(db_session_factory):
    # Setup
    tenant_id = "test-tenant-456"

    async with db_session_factory() as session, session.begin():
        from platform_orm.models.identity import Tenant, User

        tenant = Tenant(
            id=tenant_id,
            name="Test Tenant 456",
            status="ACTIVE",
        )
        user = User(id="user-123", email="test@user.com", name="Test User", status="ACTIVE")
        session.add(tenant)
        session.add(user)

    repo = PostgresInAppPersistence(db_session_factory)

    # Execute
    await repo.save_notification(
        tenant_id=tenant_id,
        content="This is the message body.",
        subject="Important Alert",
        data={"tx_id": "123", "target_user_id": "user-123"},
    )

    # Verify
    async with db_session_factory() as session:
        stmt = select(InAppNotification).where(InAppNotification.tenant_id == tenant_id)
        result = await session.execute(stmt)
        notification = result.scalar_one_or_none()

        assert notification is not None
        assert notification.title == "Important Alert"
        assert notification.body == "This is the message body."
        assert notification.is_read is False
        assert notification.tenant_id == tenant_id
        assert notification.user_id == "user-123"
