import pytest
from database.models.identity import Role, Tenant, User, UserRole
from database.models.notifications import NotificationRecord
from seedwork import generate_id, generate_random_hex

from notification.adapters.outbound.database.postgres_notification_query_repository import (
    SqlAlchemyNotificationQueryRepository,
)


@pytest.mark.asyncio
async def test_notification_query_and_mark_read(db_session_factory):
    tenant_id = f"test-query-tenant-{generate_random_hex(6)}"
    from identity.domain.constants import DomainIdPrefix as IamPrefix

    user_id = generate_id(IamPrefix.USER)
    notif_id = f"notif_inapp_{generate_random_hex(6)}"

    # Setup Data
    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name=f"Test Tenant {generate_random_hex(6)}",
            slug=tenant_id,
            status="ACTIVE",
        )
        session.add(tenant)

        user_model = User(id=user_id, email="test@test.com", name="Test User")
        session.add(user_model)

        await session.flush()

        role = Role(
            id=generate_id(IamPrefix.ROLE),
            tenant_id=tenant_id,
            name="TenantAdmin",
            description="Admin role",
            capabilities=["users:write"],
        )
        session.add(role)
        await session.flush()

        tenant_user = UserRole(
            id=f"iam_urol_{generate_random_hex(6)}",
            tenant_id=tenant_id,
            user_id=user_id,
            role_id=role.id,
        )
        session.add(tenant_user)

        notification = NotificationRecord(
            id=notif_id,
            tenant_id=tenant_id,
            user_id=user_id,
            title="Hello",
            body="World",
            is_read=False,
        )
        session.add(notification)

    repo = SqlAlchemyNotificationQueryRepository(db_session_factory)

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
