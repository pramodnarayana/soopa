import pytest
from seedwork import generate_id
from sqlalchemy import text

from notification.adapters.outbound.database.postgres_user_preference_repository import (
    SqlAlchemyUserNotificationPreferenceRepository,
)
from notification.domain.models import Channel, UserNotificationPreference


@pytest.fixture
async def repo(db_session_factory):
    async with db_session_factory() as session:
        yield SqlAlchemyUserNotificationPreferenceRepository(session=session)


@pytest.mark.asyncio
async def test_save_and_get_preference(
    repo: SqlAlchemyUserNotificationPreferenceRepository, db_session_factory
):
    # Arrange
    from identity.domain.constants import DomainIdPrefix as IamPrefix

    tenant_id = generate_id(IamPrefix.TENANT)

    user_id = generate_id(IamPrefix.USER)
    event_type = "invoice.payment_failed"
    channel = "EMAIL"

    # Insert a dummy tenant and user so the foreign keys don't blow up
    async with db_session_factory() as session:
        await session.execute(
            text(
                f"INSERT INTO identity.tenants (id, name, slug, status, created_at, updated_at) VALUES ('{tenant_id}', 'Test Tenant {tenant_id}', '{tenant_id}', 'active', NOW(), NOW()) ON CONFLICT DO NOTHING"  # noqa: S608
            )
        )
        await session.execute(
            text(
                f"INSERT INTO identity.users (id, email, name, status, created_at, updated_at) VALUES ('{user_id}', 'test@example.com', 'Test User', 'active', NOW(), NOW()) ON CONFLICT DO NOTHING"  # noqa: S608
            )
        )
        await session.commit()

    pref = UserNotificationPreference(
        id="notif_pref_test123",
        tenant_id=tenant_id,
        user_id=user_id,
        event_type=event_type,
        channel=Channel.EMAIL,
        is_enabled=False,
    )

    # Act
    await repo.save_preference(pref)
    fetched_pref = await repo.get_preference(tenant_id, user_id, event_type, channel)

    # Assert
    assert fetched_pref is not None
    assert fetched_pref.id == "notif_pref_test123"
    assert fetched_pref.tenant_id == tenant_id
    assert fetched_pref.user_id == user_id
    assert fetched_pref.event_type == event_type
    assert fetched_pref.channel == Channel.EMAIL
    assert fetched_pref.is_enabled is False

    # Act 2: Update existing (Upsert test)
    pref_updated = UserNotificationPreference(
        id="notif_pref_test123",
        tenant_id=tenant_id,
        user_id=user_id,
        event_type=event_type,
        channel=Channel.EMAIL,
        is_enabled=True,
    )
    await repo.save_preference(pref_updated)
    fetched_updated = await repo.get_preference(tenant_id, user_id, event_type, channel)

    # Assert 2
    assert fetched_updated is not None
    assert fetched_updated.is_enabled is True
