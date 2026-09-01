from datetime import UTC, datetime

import pytest
from identity.domain.constants import IdentityIdPrefix
from seedwork.utils import generate_id

from ucp.application.dto import UnsubscribeAppCommand
from ucp.application.use_cases.unsubscribe_app_use_case import UnsubscribeAppUseCase
from ucp.domain.constants import LifecycleStatus, UcpIdPrefix
from ucp.domain.models.tenant import Tenant, TenantSubscription
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def tenant_id() -> str:
    return generate_id(IdentityIdPrefix.TENANT)


@pytest.fixture
def app_id() -> str:
    return generate_id(UcpIdPrefix.APP)


@pytest.fixture
def fake_uow(tenant_id: str, app_id: str) -> FakeUcpUnitOfWork:
    uow = FakeUcpUnitOfWork()

    tenant = Tenant(
        id=tenant_id,
        name="Test Tenant",
        slug="test-tenant",
        idp_tenant_id="idp_org_123",
        status=LifecycleStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        subscriptions=[TenantSubscription(app_id=app_id, status=LifecycleStatus.ACTIVE)],
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
    tenant_id: str,
    app_id: str,
) -> None:
    command = UnsubscribeAppCommand(tenant_id=tenant_id, app_id=app_id)

    await unsubscribe_use_case.execute(command, idempotency_key="idemp-1")

    assert fake_uow.committed is True
    assert len(fake_uow.tenant_repo.saved_tenants) == 1

    saved_tenant = fake_uow.tenant_repo.saved_tenants[0]
    assert saved_tenant.id == tenant_id

    # Check subscription
    assert len(saved_tenant.subscriptions) == 1
    assert saved_tenant.subscriptions[0].app_id == app_id
    from ucp.domain.constants import LifecycleStatus

    assert saved_tenant.subscriptions[0].status == LifecycleStatus.INACTIVE

    # Check domain event
    assert len(saved_tenant.domain_events) == 1
    event = saved_tenant.domain_events[0]
    assert event.tenant_id == tenant_id
    assert event.app_id == app_id
