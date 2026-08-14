from unittest.mock import AsyncMock, create_autospec

import pytest

from ucp.application.use_cases.create_user_use_case import (
    CreateUserCommand,
    CreateUserUseCase,
)
from ucp.core.exceptions import ResourceNotFoundError
from ucp.domain.models.tenant import Tenant
from ucp.ports.outbound.tenant_repository import ITenantRepository
from ucp.ports.outbound.user_identity_provider import IUserIdentityProvider
from ucp.ports.outbound.user_repository import IUserRepository
from ucp.ports.uow import UcpUnitOfWorkPort


@pytest.fixture
def mock_tenant_repo() -> ITenantRepository:
    return create_autospec(ITenantRepository, instance=True)  # type: ignore


@pytest.fixture
def mock_user_repo() -> IUserRepository:
    return create_autospec(IUserRepository, instance=True)  # type: ignore


@pytest.fixture
def mock_idp() -> IUserIdentityProvider:
    mock = create_autospec(IUserIdentityProvider, instance=True)
    mock.create_user = AsyncMock(return_value="idp-user-123")
    return mock  # type: ignore


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
def use_case(
    mock_uow: UcpUnitOfWorkPort,
) -> CreateUserUseCase:
    return CreateUserUseCase(
        uow=mock_uow,
    )


@pytest.mark.asyncio
async def test_invite_user_success(
    use_case: CreateUserUseCase,
    mock_tenant_repo: ITenantRepository,
    mock_user_repo: IUserRepository,
    mock_uow: UcpUnitOfWorkPort,
) -> None:
    # Arrange
    tenant = Tenant.create(
        id="ten_123", name="Test", slug="test", idp_tenant_id="org-123", subscriptions=[]
    )
    mock_tenant_repo.find_by_id = AsyncMock(return_value=tenant)  # type: ignore
    command = CreateUserCommand(
        tenant_id="ten_123",
        email="test@example.com",
        first_name="John",
        last_name="Doe",
        role="admin",
    )

    # Act
    local_user_id = await use_case.execute(command)

    # Assert
    saved_user = mock_user_repo.save.call_args_list[-1][0][0]  # type: ignore
    assert saved_user.email == "test@example.com"
    assert saved_user.id == local_user_id
    assert saved_user.idp_user_id is None

    mock_user_repo.save_tenant_membership.assert_called_once_with(  # type: ignore
        tenant_id="ten_123", user_id=local_user_id, role="admin"
    )


@pytest.mark.asyncio
async def test_invite_user_tenant_not_found(
    use_case: CreateUserUseCase,
    mock_tenant_repo: ITenantRepository,
) -> None:
    # Arrange
    mock_tenant_repo.find_by_id = AsyncMock(return_value=None)  # type: ignore
    command = CreateUserCommand(
        tenant_id="ten_123",
        email="test@example.com",
        first_name="John",
        last_name="Doe",
        role="admin",
    )

    # Act / Assert
    with pytest.raises(ResourceNotFoundError):
        await use_case.execute(command)
