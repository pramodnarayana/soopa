from contextlib import asynccontextmanager

import pytest

from ucp.application.use_cases.infrastructure_provisioner import InfrastructureProvisioner
from ucp.domain.models.app import App
from ucp.ports.outbound.ucp_event_consumer_port import UcpEventMessage
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow():
    return FakeUcpUnitOfWork()


@pytest.fixture
def provisioner(fake_uow):
    @asynccontextmanager
    async def fake_factory():
        yield fake_uow

    return InfrastructureProvisioner(uow_factory=fake_factory)


@pytest.mark.asyncio
async def test_handle_app_subscribed_success(provisioner, fake_uow):
    # Setup App
    app = App(id="app_edi", name="EDI", description="EDI App", slug="edi")
    fake_uow.app_repo.apps.append(app)

    event = UcpEventMessage(
        id="evt_123",
        tenant_id="ten_123",
        event_type="app.subscribed",
        payload={"app_id": "app_edi"},
    )

    await provisioner.handle_app_subscribed(event)

    assert fake_uow.committed is True
    assert fake_uow.tenant_repo.subscriptions.get(("ten_123", "app_edi")) == "active"
    assert ("ten_123", "app_edi", "edi_shard_1") in fake_uow.tenant_repo.allocations


@pytest.mark.asyncio
async def test_handle_app_unsubscribed_success(provisioner, fake_uow):
    # Setup App
    app = App(id="app_edi", name="EDI", description="EDI App", slug="edi")
    fake_uow.app_repo.apps.append(app)

    event = UcpEventMessage(
        id="evt_123",
        tenant_id="ten_123",
        event_type="app.unsubscribed",
        payload={"app_id": "app_edi"},
    )

    await provisioner.handle_app_unsubscribed(event)

    assert fake_uow.committed is True
    assert fake_uow.tenant_repo.subscriptions.get(("ten_123", "app_edi")) == "inactive"
