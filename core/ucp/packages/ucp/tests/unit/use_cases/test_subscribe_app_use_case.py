from datetime import UTC, datetime

import pytest

from ucp.application.dto import SubscribeAppCommand
from ucp.application.use_cases.subscribe_app_use_case import SubscribeAppUseCase
from ucp.domain.models.tenant import Tenant
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow() -> FakeUcpUnitOfWork:
    uow = FakeUcpUnitOfWork()

    tenant = Tenant(
        id="ten_123",
        name="Test Tenant",
        slug="test-tenant",
        idp_tenant_id="idp_org_123",
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        subscriptions=[],
    )
    uow.tenant_repo.tenants.append(tenant)
    return uow


@pytest.fixture
def subscribe_use_case(fake_uow: FakeUcpUnitOfWork) -> SubscribeAppUseCase:
    return SubscribeAppUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_subscribe_app_success(
    subscribe_use_case: SubscribeAppUseCase,
    fake_uow: FakeUcpUnitOfWork,
) -> None:
    command = SubscribeAppCommand(tenant_id="ten_123", app_id="app_456")

    await subscribe_use_case.execute(command, idempotency_key="idemp-1")

    assert fake_uow.committed is True
    assert len(fake_uow.tenant_repo.saved_tenants) == 1

    saved_tenant = fake_uow.tenant_repo.saved_tenants[0]
    assert saved_tenant.id == "ten_123"

    # Check subscription
    assert len(saved_tenant.subscriptions) == 1
    assert saved_tenant.subscriptions[0].app_id == "app_456"
    assert saved_tenant.subscriptions[0].status == "active"

    # Check domain event
    assert len(saved_tenant.domain_events) == 1
    event = saved_tenant.domain_events[0]
    assert event.tenant_id == "ten_123"
    assert event.app_id == "app_456"
