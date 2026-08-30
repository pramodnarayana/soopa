from datetime import UTC, datetime

import pytest

from ucp.application.dto import UnsubscribeAppCommand
from ucp.application.use_cases.unsubscribe_app_use_case import UnsubscribeAppUseCase
from ucp.domain.models.tenant import Tenant, TenantSubscription
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
        subscriptions=[TenantSubscription(app_id="app_456", status="active")],
    )
    uow.tenant_repo.tenants.append(tenant)
    return uow


@pytest.fixture
def unsubscribe_use_case(fake_uow: FakeUcpUnitOfWork) -> UnsubscribeAppUseCase:
    return UnsubscribeAppUseCase(uow=fake_uow)


@pytest.mark.asyncio
async def test_unsubscribe_app_success(
    unsubscribe_use_case: UnsubscribeAppUseCase,
    fake_uow: FakeUcpUnitOfWork,
) -> None:
    command = UnsubscribeAppCommand(tenant_id="ten_123", app_id="app_456")

    await unsubscribe_use_case.execute(command, idempotency_key="idemp-1")

    assert fake_uow.committed is True
    assert len(fake_uow.tenant_repo.saved_tenants) == 1

    saved_tenant = fake_uow.tenant_repo.saved_tenants[0]
    assert saved_tenant.id == "ten_123"

    # Check subscription
    assert len(saved_tenant.subscriptions) == 1
    assert saved_tenant.subscriptions[0].app_id == "app_456"
    assert saved_tenant.subscriptions[0].status == "inactive"

    # Check domain event
    assert len(saved_tenant.domain_events) == 1
    event = saved_tenant.domain_events[0]
    assert event.tenant_id == "ten_123"
    assert event.app_id == "app_456"
