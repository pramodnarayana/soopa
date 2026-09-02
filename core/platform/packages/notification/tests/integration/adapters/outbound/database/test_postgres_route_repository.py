import pytest
from database.models.identity import Tenant
from database.models.notifications import NotificationRouteConfiguration
from seedwork import generate_id, generate_random_hex
from ucp.domain.constants import LifecycleStatus

from notification.adapters.outbound.database.postgres_route_repository import (
    SqlAlchemyNotificationRouteRepository,
)
from notification.domain.constants import NotificationIdPrefix
from notification.domain.models import Channel


@pytest.mark.asyncio
async def test_get_channels_returns_configured_channels(db_session_factory):
    # Setup test data
    tenant_id = f"test-tenant-123-{generate_random_hex(6)}"
    event_type = "test.event.fired"

    async with db_session_factory() as session, session.begin():
        # Because foreign keys are enforced, we must create the tenant first

        tenant = Tenant(
            id=tenant_id,
            name=f"Test Tenant {generate_random_hex(6)}",
            slug=tenant_id,
            status=LifecycleStatus.ACTIVE,
        )
        session.add(tenant)

        route = NotificationRouteConfiguration(
            id=generate_id(NotificationIdPrefix.ROUTE),
            tenant_id=tenant_id,
            event_type=event_type,
            channels=["EMAIL", "IN_APP"],
        )
        session.add(route)

    async with db_session_factory() as session:
        repo = SqlAlchemyNotificationRouteRepository(session)
        channels = await repo.get_channels(tenant_id, event_type)

    # Verify
    assert len(channels) == 2
    assert Channel.EMAIL in channels
    assert Channel.IN_APP in channels


@pytest.mark.asyncio
async def test_get_channels_returns_empty_when_no_route(db_session_factory):
    async with db_session_factory() as session:
        repo = SqlAlchemyNotificationRouteRepository(session)
        channels = await repo.get_channels("non-existent", "test.event.fired")
        assert channels == []


@pytest.mark.asyncio
async def test_postgres_route_repository_crud_operations(db_session_factory):
    tenant_id = f"test-tenant-123-{generate_random_hex(6)}"
    event_type = "test.crud.event"

    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name=f"Test Tenant {generate_random_hex(6)}",
            slug=tenant_id,
            status=LifecycleStatus.ACTIVE,
        )
        session.add(tenant)

    async with db_session_factory() as session:
        repo = SqlAlchemyNotificationRouteRepository(session)

        # 1. Initially empty list
        prefs = await repo.list_preferences(tenant_id)
        assert len(prefs) == 0

        # 2. Upsert
        pref = await repo.upsert_preference(
            tenant_id=tenant_id,
            event_type=event_type,
            channels=["EMAIL", "SLACK"],
        )
        await session.commit()

        assert pref.tenant_id == tenant_id
        assert pref.event_type == event_type
        assert len(pref.channels) == 2

        # 3. List preferences
        prefs = await repo.list_preferences(tenant_id)
        assert len(prefs) == 1
        assert prefs[0].event_type == event_type

        # 4. Upsert (update existing)
        pref2 = await repo.upsert_preference(
            tenant_id=tenant_id,
            event_type=event_type,
            channels=["IN_APP"],
        )
        await session.commit()
        assert len(pref2.channels) == 1

        # 5. Get channels directly
        channels = await repo.get_channels(tenant_id, event_type)
        assert len(channels) == 1
        assert channels[0].value == "IN_APP"

        # 6. Delete
        deleted = await repo.delete_preference(tenant_id, event_type)
        await session.commit()
        assert deleted is True

        # 7. Delete again
        deleted_again = await repo.delete_preference(tenant_id, event_type)
        await session.commit()
        assert deleted_again is False
