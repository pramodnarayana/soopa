from unittest.mock import AsyncMock, create_autospec

import pytest

from ucp.application.use_cases.provision_tenant_use_case import (
    ProvisionTenantCommand,
    ProvisionTenantUseCase,
)
from ucp.ports.outbound.organization_provider_port import OrganizationProviderPort
from ucp.ports.outbound.role_repository_port import RoleRepositoryPort
from ucp.ports.outbound.tenant_repository_port import TenantRepositoryPort
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort
from ucp.ports.outbound.user_identity_provider_port import UserIdentityProviderPort


@pytest.fixture
def mock_tenant_repo() -> TenantRepositoryPort:
    """Strict mock that enforces the TenantRepositoryPort port interface."""
    return create_autospec(TenantRepositoryPort, instance=True)


@pytest.fixture
def mock_role_repo() -> RoleRepositoryPort:
    """Strict mock that enforces the RoleRepositoryPort port interface."""
    mock = create_autospec(RoleRepositoryPort, instance=True)

    # Mock the global role return
    from ucp.domain.models.authorization import Role

    tenant_admin_role = Role(
        id="rol_tenant_admin_123",
        tenant_id=None,
        name="Tenant Admin",
        description="Tenant Admin Role",
        capabilities=["tenant:admin"],
    )
    mock.get_global_role_by_name = AsyncMock(return_value=tenant_admin_role)
    mock.assign_user_role = AsyncMock(return_value=None)

    return mock


@pytest.fixture
def mock_org_provider() -> OrganizationProviderPort:
    """Strict mock that enforces the OrganizationProviderPort port interface."""
    mock = create_autospec(OrganizationProviderPort, instance=True)
    mock.create_organization = AsyncMock(return_value=("zitadel-org-123", "org-name"))
    return mock


@pytest.fixture
def mock_user_identity_provider() -> UserIdentityProviderPort:
    """Strict mock that enforces the UserIdentityProviderPort port interface."""
    return create_autospec(UserIdentityProviderPort, instance=True)


@pytest.fixture
def mock_uow(
    mock_tenant_repo: TenantRepositoryPort, mock_role_repo: RoleRepositoryPort
) -> UcpUnitOfWorkPort:
    uow = create_autospec(UcpUnitOfWorkPort, instance=True)
    uow.tenant_repo = mock_tenant_repo
    uow.role_repo = mock_role_repo

    # Mock user_repo
    from ucp.ports.outbound.user_repository_port import UserRepositoryPort

    mock_user_repo = create_autospec(UserRepositoryPort, instance=True)
    from ucp.domain.models.user import User

    async def mock_find_by_id(user_id: str) -> User | None:
        from datetime import UTC, datetime

        return User(
            id=user_id,
            idp_user_id="idp_creator_123",
            email="creator@example.com",
            name="Creator",
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    mock_user_repo.find_by_id = AsyncMock(side_effect=mock_find_by_id)
    uow.user_repo = mock_user_repo

    uow.__aenter__.return_value = uow
    return uow


@pytest.fixture
def provision_use_case(
    mock_uow: UcpUnitOfWorkPort,
) -> ProvisionTenantUseCase:
    return ProvisionTenantUseCase(
        uow=mock_uow,
    )


@pytest.mark.asyncio
async def test_provision_tenant_success(
    provision_use_case: ProvisionTenantUseCase,
    mock_tenant_repo: TenantRepositoryPort,
    mock_role_repo: RoleRepositoryPort,
    mock_uow: UcpUnitOfWorkPort,
) -> None:
    # Arrange
    command = ProvisionTenantCommand(name="Test Tenant", creator_id="usr_creator_123")

    # Act
    tenant = await provision_use_case.execute(command, idempotency_key="idemp-1")

    # Assert - correct calls to the ports
    mock_tenant_repo.save.assert_called_once()

    # Assert — the tenant passed to save is correct
    saved_tenant = mock_tenant_repo.save.call_args[0][0]
    assert saved_tenant.name == "Test Tenant"
    assert saved_tenant.idp_tenant_id is None
    assert saved_tenant.id.startswith("ten_")

    # Assert \u2014 the returned tenant is the same object persisted
    assert tenant is saved_tenant

    # Assert \u2014 a provisioned domain event was raised
    assert len(tenant.domain_events) == 1
    assert tenant.domain_events[0].tenant_id == tenant.id
    assert tenant.domain_events[0].tenant_name == "Test Tenant"
