from unittest.mock import AsyncMock, create_autospec

import pytest

from ucp.application.use_cases.provision_tenant_use_case import (
    ProvisionTenantCommand,
    ProvisionTenantUseCase,
)
from ucp.ports.outbound.organization_provider import IOrganizationProvider
from ucp.ports.outbound.tenant_repository import ITenantRepository
from ucp.ports.outbound.user_identity_provider import IUserIdentityProvider


@pytest.fixture
def mock_tenant_repo() -> ITenantRepository:
    """Strict mock that enforces the ITenantRepository port interface."""
    return create_autospec(ITenantRepository, instance=True)  # type: ignore


@pytest.fixture
def mock_org_provider() -> IOrganizationProvider:
    """Strict mock that enforces the IOrganizationProvider port interface."""
    mock = create_autospec(IOrganizationProvider, instance=True)
    mock.create_organization = AsyncMock(return_value=("zitadel-org-123", "org-name"))
    return mock  # type: ignore


@pytest.fixture
def mock_user_identity_provider() -> IUserIdentityProvider:
    """Strict mock that enforces the IUserIdentityProvider port interface."""
    return create_autospec(IUserIdentityProvider, instance=True)  # type: ignore


@pytest.fixture
def provision_use_case(
    mock_tenant_repo: ITenantRepository,
    mock_org_provider: IOrganizationProvider,
    mock_user_identity_provider: IUserIdentityProvider,
) -> ProvisionTenantUseCase:
    return ProvisionTenantUseCase(
        tenant_repo=mock_tenant_repo,
        organization_provider=mock_org_provider,
        user_identity_provider=mock_user_identity_provider,
    )


@pytest.mark.asyncio
async def test_provision_tenant_success(
    provision_use_case: ProvisionTenantUseCase,
    mock_tenant_repo: ITenantRepository,
    mock_org_provider: IOrganizationProvider,
) -> None:
    # Arrange
    command = ProvisionTenantCommand(name="Test Tenant")

    # Act
    tenant = await provision_use_case.execute(command, idempotency_key="idemp-1")

    # Assert \u2014 correct calls to the ports
    mock_org_provider.create_organization.assert_called_once_with("Test Tenant")  # type: ignore
    mock_tenant_repo.save.assert_called_once()  # type: ignore

    # Assert \u2014 the tenant passed to save is correct
    saved_tenant = mock_tenant_repo.save.call_args[0][0]  # type: ignore
    assert saved_tenant.name == "Test Tenant"
    assert saved_tenant.idp_tenant_id == "zitadel-org-123"
    assert saved_tenant.id.startswith("ten_")

    # Assert \u2014 the returned tenant is the same object persisted
    assert tenant is saved_tenant

    # Assert \u2014 a provisioned domain event was raised
    assert len(tenant.domain_events) == 1
    assert tenant.domain_events[0].tenant_id == tenant.id
    assert tenant.domain_events[0].tenant_name == "Test Tenant"
