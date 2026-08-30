import pytest
from identity.domain.models.user import User

from ucp.application.use_cases.delete_tenant_use_case import DeleteTenantUseCase
from ucp.domain.exceptions import ResourceNotFoundError
from ucp.domain.models.tenant import Tenant
from ucp.testing.fakes import FakeUcpUnitOfWork


@pytest.fixture
def fake_uow() -> FakeUcpUnitOfWork:
    return FakeUcpUnitOfWork()


@pytest.fixture
def delete_use_case(
    fake_uow: FakeUcpUnitOfWork,
) -> DeleteTenantUseCase:
    return DeleteTenantUseCase(
        uow=fake_uow,
    )


@pytest.mark.asyncio
async def test_delete_tenant_not_found(
    delete_use_case: DeleteTenantUseCase,
    fake_uow: FakeUcpUnitOfWork,
) -> None:
    with pytest.raises(ResourceNotFoundError):
        await delete_use_case.execute("ten_invalid")


@pytest.mark.asyncio
async def test_delete_tenant_success(
    delete_use_case: DeleteTenantUseCase,
    fake_uow: FakeUcpUnitOfWork,
) -> None:
    tenant = Tenant.create(
        id="ten_123",
        name="Test",
        slug="test",
        idp_tenant_id="zitadel-org-123",
        subscriptions=[],
    )
    fake_uow.tenant_repo.tenants.append(tenant)

    mock_user = User.create(
        id="usr_1", idp_user_id="zitadel-user-1", email="test@test.com", name="Test User"
    )
    fake_uow.user_repo.users.append(mock_user)

    await delete_use_case.execute("ten_123", "idemp-key")

    assert tenant.deleted_at is not None
    assert tenant not in fake_uow.tenant_repo.tenants
    assert mock_user.deleted_at is not None
    assert mock_user not in fake_uow.user_repo.users

    assert fake_uow.committed is True
