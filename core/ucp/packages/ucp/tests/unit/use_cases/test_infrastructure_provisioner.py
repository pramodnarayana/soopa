from contextlib import asynccontextmanager

import pytest
from identity.domain.constants import IdentityIdPrefix
from seedwork.utils import generate_id

from ucp.application.use_cases.infrastructure_provisioner import InfrastructureProvisioner
from ucp.domain.constants import LifecycleStatus, UcpEventType, UcpIdPrefix
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
    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    app_id = generate_id(UcpIdPrefix.APP)

    app = App(id=app_id, name="EDI", description="EDI App", slug="edi")
    fake_uow.app_repo.apps.append(app)

    event = UcpEventMessage(
        id=generate_id(IdentityIdPrefix.TOKEN),
        tenant_id=tenant_id,
        event_type=UcpEventType.APP_SUBSCRIBED.value,
        payload={"app_id": app_id},
    )

    await provisioner.handle_app_subscribed(event)

    assert fake_uow.committed is True

    assert fake_uow.tenant_repo.subscriptions.get((tenant_id, app_id)) == LifecycleStatus.ACTIVE
    assert (tenant_id, app_id, "edi_shard_1") in fake_uow.tenant_repo.allocations


@pytest.mark.asyncio
async def test_handle_app_unsubscribed_success(provisioner, fake_uow):
    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    app_id = generate_id(UcpIdPrefix.APP)

    app = App(id=app_id, name="EDI", description="EDI App", slug="edi")
    fake_uow.app_repo.apps.append(app)

    event = UcpEventMessage(
        id=generate_id(IdentityIdPrefix.TOKEN),
        tenant_id=tenant_id,
        event_type=UcpEventType.APP_UNSUBSCRIBED.value,
        payload={"app_id": app_id},
    )

    await provisioner.handle_app_unsubscribed(event)

    assert fake_uow.committed is True

    assert fake_uow.tenant_repo.subscriptions.get((tenant_id, app_id)) == LifecycleStatus.INACTIVE
