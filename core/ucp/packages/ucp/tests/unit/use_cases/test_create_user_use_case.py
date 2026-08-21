from unittest.mock import AsyncMock, create_autospec

import pytest

from ucp.application.use_cases.create_user_use_case import (
    CreateUserCommand,
    CreateUserUseCase,
)
from ucp.domain.exceptions import ResourceNotFoundError
from ucp.domain.models.tenant import Tenant
from ucp.ports.outbound.tenant_repository_port import TenantRepositoryPort
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort
from ucp.ports.outbound.user_identity_provider_port import UserIdentityProviderPort
from ucp.ports.outbound.user_repository_port import UserRepositoryPort


@pytest.fixture
def mock_tenant_repo() -> TenantRepositoryPort:
    return create_autospec(TenantRepositoryPort, instance=True)


@pytest.fixture
def mock_user_repo() -> UserRepositoryPort:
    return create_autospec(UserRepositoryPort, instance=True)


@pytest.fixture
def mock_idp() -> UserIdentityProviderPort:
    mock = create_autospec(UserIdentityProviderPort, instance=True)
    mock.create_user = AsyncMock(return_value="idp-user-123")
    return mock


from ucp.domain.models.authorization import Role
from ucp.ports.outbound.role_repository_port import RoleRepositoryPort


@pytest.fixture
def mock_role_repo() -> RoleRepositoryPort:
    return create_autospec(RoleRepositoryPort, instance=True)


@pytest.fixture
def mock_uow(
    mock_tenant_repo: TenantRepositoryPort,
    mock_user_repo: UserRepositoryPort,
    mock_role_repo: RoleRepositoryPort,
) -> UcpUnitOfWorkPort:
    uow = create_autospec(UcpUnitOfWorkPort, instance=True)
    uow.tenant_repo = mock_tenant_repo
    uow.user_repo = mock_user_repo
    uow.role_repo = mock_role_repo
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
    mock_tenant_repo: TenantRepositoryPort,
    mock_user_repo: UserRepositoryPort,
    mock_role_repo: RoleRepositoryPort,
    mock_uow: UcpUnitOfWorkPort,
) -> None:
    # Arrange
    tenant = Tenant.create(
        id="ten_123", name="Test", slug="test", idp_tenant_id="org-123", subscriptions=[]
    )
    mock_tenant_repo.find_by_id = AsyncMock(return_value=tenant)

    mock_role = Role(id="role_123", tenant_id=None, name="Tenant Admin", description="")
    mock_role_repo.get_global_role_by_name = AsyncMock(return_value=mock_role)

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
    saved_user = mock_user_repo.save.call_args_list[-1][0][0]
    assert saved_user.email == "test@example.com"
    assert saved_user.id == local_user_id
    assert saved_user.idp_user_id is None

    # Verify UserRoleAssignedEvent was added
    role_events = [e for e in saved_user.domain_events if e.event_name == "user_role_assigned"]
    assert len(role_events) == 1
    assert role_events[0].role_id == "role_123"
    assert role_events[0].tenant_id == "ten_123"


@pytest.mark.asyncio
async def test_invite_user_tenant_not_found(
    use_case: CreateUserUseCase,
    mock_tenant_repo: TenantRepositoryPort,
) -> None:
    # Arrange
    mock_tenant_repo.find_by_id = AsyncMock(return_value=None)
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
