from __future__ import annotations

import asyncio
import typing

import pytest

from edi.application.use_cases.authorization.get_authorization_profile_use_case import (
    GetAuthorizationProfileQuery,
    GetAuthorizationProfileUseCase,
)
from edi.domain.authorization import TenantFeatureFlags
from edi.testing.fakes.api_fakes import FakeTenantRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def use_case() -> GetAuthorizationProfileUseCase:
    tenant_repo = FakeTenantRepository()
    return GetAuthorizationProfileUseCase(tenant_repo=tenant_repo)


@pytest.mark.asyncio
async def test_authorization_platform_admin(
    use_case: GetAuthorizationProfileUseCase,
) -> None:
    tenant_repo = typing.cast(FakeTenantRepository, use_case.tenant_repo)
    tenant_repo.flags["0"] = TenantFeatureFlags(allow_private_as2=True)

    project_roles: dict[str, dict[str, str]] = {"Platform_Admin": {}}
    is_platform_admin = "Platform_Admin" in project_roles

    profile = (
        await use_case.execute(
            GetAuthorizationProfileQuery(
                tenant_id="0",
                is_platform_admin=is_platform_admin,
                current_rls_tenant="0",
            )
        )
    ).to_dict()

    assert profile["status"] == "success"
    assert profile["tenant_id"] == "0"
    assert profile["is_platform_admin"] is True
    assert profile["allow_private_as2"] is True
    assert profile["role"] == "Owner"
    permissions = profile["permissions"]
    assert isinstance(permissions, list)
    assert "users:read" in permissions
    assert "users:write" in permissions
    assert "routes:manage" in permissions
    assert profile["rls_enforced_tenant"] == "0"


@pytest.mark.asyncio
async def test_authorization_standard_user(
    use_case: GetAuthorizationProfileUseCase,
) -> None:
    tenant_repo = typing.cast(FakeTenantRepository, use_case.tenant_repo)
    tenant_repo.flags["1"] = TenantFeatureFlags(allow_private_as2=False)

    project_roles: dict[str, dict[str, str]] = {}
    is_platform_admin = "Platform_Admin" in project_roles

    profile = (
        await use_case.execute(
            GetAuthorizationProfileQuery(
                tenant_id="1",
                is_platform_admin=is_platform_admin,
                current_rls_tenant="1",
            )
        )
    ).to_dict()

    assert profile["status"] == "success"
    assert profile["tenant_id"] == "1"
    assert profile["is_platform_admin"] is False
    assert profile["allow_private_as2"] is False
    assert profile["role"] == "Standard"
    permissions = profile["permissions"]
    assert isinstance(permissions, list)
    assert "users:read" in permissions
    assert "users:write" not in permissions
    assert profile["rls_enforced_tenant"] == "1"


def test_authorization_platform_admin_explicit_grant() -> None:
    repo = FakeTenantRepository()
    use_case = GetAuthorizationProfileUseCase(repo)
    profile = asyncio.run(
        use_case.execute(
            GetAuthorizationProfileQuery(
                tenant_id="0",
                is_platform_admin=True,
                current_rls_tenant=None,
            )
        )
    ).to_dict()
    assert profile["is_platform_admin"] is True
    assert profile["role"] == "Owner"
