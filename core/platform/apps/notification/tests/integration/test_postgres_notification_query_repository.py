import uuid

import pytest
from platform_orm.models.identity import Role, Tenant, User, UserRole
from platform_orm.models.notifications import InAppNotification

from notification.adapters.outbound.postgres_notification_query_repository import (
    PostgresNotificationQueryRepository,
)


@pytest.mark.asyncio
async def test_notification_query_and_mark_read(db_session_factory):
    tenant_id = "test-query-tenant"
    user_id = "test-user-123"
    notif_id = f"notif_inapp_{uuid.uuid4().hex}"

    # Setup Data
    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name="Test Tenant",
            slug=tenant_id,
            status="ACTIVE",
        )
        session.add(tenant)

        user_model = User(id=user_id, email="test@test.com", name="Test User")
        session.add(user_model)

        await session.flush()

        role = Role(
            id=f"rol_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            name="TenantAdmin",
            description="Admin role",
            capabilities=["users:write"],
        )
        session.add(role)
        await session.flush()

        tenant_user = UserRole(
            id=f"urol_{uuid.uuid4().hex}", tenant_id=tenant_id, user_id=user_id, role_id=role.id
        )
        session.add(tenant_user)

        notification = InAppNotification(
            id=notif_id,
            tenant_id=tenant_id,
            user_id=user_id,
            title="Hello",
            body="World",
            is_read=False,
        )
        session.add(notification)

    repo = PostgresNotificationQueryRepository(db_session_factory)

    # Query
    dtos = await repo.get_in_app_notifications(tenant_id, user_id, limit=10)
    assert len(dtos) == 1
    assert dtos[0].id == notif_id
    assert dtos[0].title == "Hello"
    assert dtos[0].is_read is False

    # Mark as read
    success = await repo.mark_as_read(tenant_id, user_id, notif_id)
    assert success is True

    # Query again
    dtos2 = await repo.get_in_app_notifications(tenant_id, user_id, limit=10)
    assert dtos2[0].is_read is True

    # Try marking read a non-existent one
    success2 = await repo.mark_as_read(tenant_id, user_id, "non_existent")
    assert success2 is False
