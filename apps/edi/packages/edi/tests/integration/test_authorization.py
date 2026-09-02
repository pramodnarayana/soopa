import asyncio
import typing
from typing import Any

import pytest

from edi.domain.authorization import AuthorizationService
from edi.testing.fakes.api_fakes import FakeTenantRepository


@pytest.fixture
def service():
    tenant_repo = FakeTenantRepository()
    return AuthorizationService(tenant_repo=tenant_repo)


@pytest.mark.asyncio
async def test_authorization_platform_admin(service: AuthorizationService):

    tenant_repo = typing.cast(FakeTenantRepository, service.tenant_repo)
    tenant_repo.flags["0"] = {"allow_private_as2": True}

    # Platform Admin status comes only from the trusted role claim in the token
    token_payload: dict[str, Any] = {"urn:zitadel:iam:org:project:roles": {"Platform_Admin": {}}}
    is_platform_admin = "Platform_Admin" in token_payload.get(
        "urn:zitadel:iam:org:project:roles", {}
    )

    profile = await service.get_authorization_profile(
        tenant_id="0", is_platform_admin=is_platform_admin, current_rls_tenant="0"
    )

    assert profile["status"] == "success"
    assert profile["tenant_id"] == "0"
    assert profile["is_platform_admin"] is True
    assert profile["allow_private_as2"] is True
    assert profile["role"] == "Owner"
    assert "users:read" in profile["permissions"]
    assert "users:write" in profile["permissions"]
    assert "routes:manage" in profile["permissions"]
    assert profile["rls_enforced_tenant"] == "0"


@pytest.mark.asyncio
async def test_authorization_standard_user(service: AuthorizationService):

    tenant_repo = typing.cast(FakeTenantRepository, service.tenant_repo)
    tenant_repo.flags["1"] = {"allow_private_as2": False}

    token_payload: dict[str, Any] = {"urn:zitadel:iam:org:project:roles": {}}
    is_platform_admin = "Platform_Admin" in token_payload.get(
        "urn:zitadel:iam:org:project:roles", {}
    )

    profile = await service.get_authorization_profile(
        tenant_id="1", is_platform_admin=is_platform_admin, current_rls_tenant="1"
    )

    assert profile["status"] == "success"
    assert profile["tenant_id"] == "1"
    assert profile["is_platform_admin"] is False
    assert profile["allow_private_as2"] is False
    assert profile["role"] == "Standard"
    assert "users:read" in profile["permissions"]
    assert "users:write" not in profile["permissions"]
    assert profile["rls_enforced_tenant"] == "1"


def test_authorization_platform_admin_explicit_grant():

    repo = FakeTenantRepository()
    svc = AuthorizationService(repo)
    profile = asyncio.run(svc.get_authorization_profile(0, True, None))
    # Explicitly passing is_platform_admin=True grants Owner role
    assert profile["is_platform_admin"] is True
    assert profile["role"] == "Owner"
