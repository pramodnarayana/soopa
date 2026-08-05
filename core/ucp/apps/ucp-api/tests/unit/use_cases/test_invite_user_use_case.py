from unittest.mock import AsyncMock, create_autospec

import pytest
from ucp_api.application.use_cases.invite_user_use_case import (
    InviteUserCommand,
    InviteUserUseCase,
)
from ucp_api.core.exceptions import ResourceNotFoundError
from ucp_api.domain.models.tenant import Tenant
from ucp_api.ports.outbound.tenant_repository import ITenantRepository
from ucp_api.ports.outbound.user_identity_provider import IUserIdentityProvider
from ucp_api.ports.outbound.user_repository import IUserRepository


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
def use_case(
    mock_tenant_repo: ITenantRepository,
    mock_user_repo: IUserRepository,
    mock_idp: IUserIdentityProvider,
) -> InviteUserUseCase:
    return InviteUserUseCase(
        tenant_repo=mock_tenant_repo,
        user_repo=mock_user_repo,
        user_identity_provider=mock_idp,
    )


@pytest.mark.asyncio
async def test_invite_user_success(
    use_case: InviteUserUseCase,
    mock_tenant_repo: ITenantRepository,
    mock_user_repo: IUserRepository,
    mock_idp: IUserIdentityProvider,
) -> None:
    # Arrange
    tenant = Tenant.create(id="ten_123", name="Test", idp_tenant_id="org-123", subscriptions=[])
    mock_tenant_repo.find_by_id = AsyncMock(return_value=tenant)  # type: ignore
    command = InviteUserCommand(
        tenant_id="ten_123",
        email="test@example.com",
        first_name="John",
        last_name="Doe",
        role="admin",
    )

    # Act
    local_user_id = await use_case.execute(command)

    # Assert
    mock_idp.create_user.assert_called_once_with(  # type: ignore
        org_id="org-123", email="test@example.com", first_name="John", last_name="Doe"
    )
    mock_idp.assign_tenant_role.assert_called_once_with(  # type: ignore
        user_id="idp-user-123", org_id="org-123", role="admin"
    )

    saved_user = mock_user_repo.save.call_args[0][0]  # type: ignore
    assert saved_user.email == "test@example.com"
    assert saved_user.id == local_user_id
    assert saved_user.idp_user_id == "idp-user-123"

    mock_user_repo.save_tenant_membership.assert_called_once_with(  # type: ignore
        tenant_id="ten_123", user_id=local_user_id, role="admin"
    )


@pytest.mark.asyncio
async def test_invite_user_tenant_not_found(
    use_case: InviteUserUseCase,
    mock_tenant_repo: ITenantRepository,
) -> None:
    # Arrange
    mock_tenant_repo.find_by_id = AsyncMock(return_value=None)  # type: ignore
    command = InviteUserCommand(
        tenant_id="ten_123",
        email="test@example.com",
        first_name="John",
        last_name="Doe",
        role="admin",
    )

    # Act / Assert
    with pytest.raises(ResourceNotFoundError):
        await use_case.execute(command)
