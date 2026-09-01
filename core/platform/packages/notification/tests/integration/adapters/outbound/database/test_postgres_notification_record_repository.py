import pytest
from database.models.notifications import NotificationRecord
from identity.domain.constants import UserStatus
from seedwork import generate_random_hex
from sqlalchemy import select
from ucp.domain.constants import LifecycleStatus

from notification.adapters.outbound.database.postgres_notification_record_repository import (
    SqlAlchemyNotificationRecordRepository,
)


@pytest.mark.asyncio
async def test_save_notification_persists_to_database(db_session_factory):
    # Setup
    tenant_id = f"test-tenant-456-{generate_random_hex(6)}"

    async with db_session_factory() as session, session.begin():
        from database.models.identity import Tenant, User

        tenant = Tenant(
            id=tenant_id,
            name="Test Tenant 456",
            slug=tenant_id,
            status=LifecycleStatus.ACTIVE,
        )
        user = User(
            id="user-123", email="test@user.com", name="Test User", status=UserStatus.ACTIVE
        )
        session.add(tenant)
        session.add(user)

    # Execute
    async with db_session_factory() as session:
        repo = SqlAlchemyNotificationRecordRepository(session)
        from notification.domain.models import Channel, NotificationDispatch

        dispatch = NotificationDispatch.create(
            tenant_id=tenant_id,
            channel=Channel.IN_APP,
            subject="Important Alert",
            body="This is the message body.",
            data={"tx_id": "123", "target_user_id": "user-123"},
            idempotency_key="idemp_123",
        )
        await repo.save(dispatch)
        await session.commit()

    # Verify
    async with db_session_factory() as session:
        stmt = select(NotificationRecord).where(NotificationRecord.tenant_id == tenant_id)
        result = await session.execute(stmt)
        notification = result.scalar_one_or_none()

        assert notification is not None
        assert notification.title == "Important Alert"
        assert notification.body == "This is the message body."
        assert notification.is_read is False
        assert notification.tenant_id == tenant_id
        assert notification.user_id == "user-123"
