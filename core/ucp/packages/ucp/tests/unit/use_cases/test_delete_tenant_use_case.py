from unittest.mock import AsyncMock, create_autospec

import pytest

from ucp.application.use_cases.delete_tenant_use_case import DeleteTenantUseCase
from ucp.core.exceptions import ResourceNotFoundError
from ucp.domain.models.tenant import Tenant
from ucp.domain.models.user import User
from ucp.ports.outbound.organization_provider import IOrganizationProvider
from ucp.ports.outbound.tenant_repository import ITenantRepository
from ucp.ports.outbound.user_repository import IUserRepository
from ucp.ports.uow import UcpUnitOfWorkPort


@pytest.fixture
def mock_tenant_repo() -> ITenantRepository:
    """Strict mock that enforces the ITenantRepository port interface."""
    return create_autospec(ITenantRepository, instance=True)  # type: ignore


@pytest.fixture
def mock_user_repo() -> IUserRepository:
    """Strict mock that enforces the IUserRepository port interface."""
    return create_autospec(IUserRepository, instance=True)  # type: ignore


@pytest.fixture
def mock_org_provider() -> IOrganizationProvider:
    """Strict mock that enforces the IOrganizationProvider port interface."""
    return create_autospec(IOrganizationProvider, instance=True)  # type: ignore


@pytest.fixture
def mock_uow(
    mock_tenant_repo: ITenantRepository, mock_user_repo: IUserRepository
) -> UcpUnitOfWorkPort:
    uow = create_autospec(UcpUnitOfWorkPort, instance=True)  # type: ignore
    uow.tenant_repo = mock_tenant_repo
    uow.user_repo = mock_user_repo
    uow.__aenter__.return_value = uow
    return uow


@pytest.fixture
def delete_use_case(
    mock_uow: UcpUnitOfWorkPort,
) -> DeleteTenantUseCase:
    return DeleteTenantUseCase(
        uow=mock_uow,
    )


@pytest.mark.asyncio
async def test_delete_tenant_not_found(
    delete_use_case: DeleteTenantUseCase,
    mock_tenant_repo: ITenantRepository,
) -> None:
    mock_tenant_repo.find_by_id = AsyncMock(return_value=None)  # type: ignore

    with pytest.raises(ResourceNotFoundError):
        await delete_use_case.execute("ten_invalid")


@pytest.mark.asyncio
async def test_delete_tenant_success(
    delete_use_case: DeleteTenantUseCase,
    mock_tenant_repo: ITenantRepository,
    mock_user_repo: IUserRepository,
    mock_uow: UcpUnitOfWorkPort,
) -> None:
    tenant = Tenant.create(
        id="ten_123",
        name="Test",
        slug="test",
        idp_tenant_id="zitadel-org-123",
        subscriptions=[],
    )
    mock_tenant_repo.find_by_id = AsyncMock(return_value=tenant)  # type: ignore

    mock_user = User.create(
        id="usr_1", idp_user_id="zitadel-user-1", email="test@test.com", name="Test User"
    )
    mock_user_repo.find_users_by_tenant = AsyncMock(return_value=[mock_user])  # type: ignore
    mock_user_repo.has_any_tenant_memberships = AsyncMock(return_value=False)  # type: ignore
    mock_tenant_repo.delete = AsyncMock()  # type: ignore
    mock_user_repo.delete = AsyncMock()  # type: ignore
    mock_org_provider.delete_organization = AsyncMock()  # type: ignore

    await delete_use_case.execute("ten_123", "idemp-key")

    mock_tenant_repo.find_by_id.assert_called_once_with("ten_123")
    mock_user_repo.find_users_by_tenant.assert_called_once_with("ten_123")
    mock_tenant_repo.delete.assert_awaited_once_with(tenant, "idemp-key")
    assert tenant.deleted_at is not None

    # User deletion assertions
    mock_user_repo.has_any_tenant_memberships.assert_awaited_once_with("usr_1")
    mock_user_repo.delete.assert_awaited_once_with(mock_user)
    assert mock_user.deleted_at is not None

    mock_uow.commit.assert_awaited_once()
