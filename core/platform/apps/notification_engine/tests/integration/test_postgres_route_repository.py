import pytest
from platform_orm.models.notifications import NotificationRouteConfiguration

from notification_engine.adapters.outbound.postgres_route_repository import PostgresRouteRepository
from notification_engine.domain.models import Channel


@pytest.mark.asyncio
async def test_get_channels_returns_configured_channels(db_session_factory):
    # Setup test data
    tenant_id = "test-tenant-123"
    event_type = "test.event.fired"

    async with db_session_factory() as session, session.begin():
        # Because foreign keys are enforced, we must create the tenant first
        from platform_orm.models.identity import Tenant

        tenant = Tenant(
            id=tenant_id,
            name="Test Tenant",
            status="ACTIVE",
        )
        session.add(tenant)

        route = NotificationRouteConfiguration(
            id="notif_rte_123",
            tenant_id=tenant_id,
            event_type=event_type,
            channels=["EMAIL", "IN_APP"],
        )
        session.add(route)

    # Execute
    repo = PostgresRouteRepository(db_session_factory)
    channels = await repo.get_channels(tenant_id, event_type)

    # Verify
    assert len(channels) == 2
    assert Channel.EMAIL in channels
    assert Channel.IN_APP in channels


@pytest.mark.asyncio
async def test_get_channels_returns_empty_when_no_route(db_session_factory):
    repo = PostgresRouteRepository(db_session_factory)
    channels = await repo.get_channels("non-existent", "test.event.fired")
    assert channels == []
