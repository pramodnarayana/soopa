import pytest
from api.core.authorization import AuthorizationService
from api_fakes import FakeTenantRepository


@pytest.fixture
def service():
    tenant_repo = FakeTenantRepository()
    return AuthorizationService(tenant_repo=tenant_repo)


@pytest.mark.asyncio
async def test_authorization_platform_admin(service: AuthorizationService):
    tenant_repo: FakeTenantRepository = service.tenant_repo
    tenant_repo.flags[0] = {"allow_private_as2": True}

    # Platform Admin status comes only from the trusted role claim in the token
    token_payload = {"urn:zitadel:iam:org:project:roles": {"Platform_Admin": {}}}

    profile = await service.get_authorization_profile(
        tenant_id=0, token_payload=token_payload, current_rls_tenant=0
    )

    assert profile["status"] == "success"
    assert profile["tenant_id"] == 0
    assert profile["is_platform_admin"] is True
    assert profile["allow_private_as2"] is True
    assert profile["role"] == "Owner"
    assert "users:read" in profile["permissions"]
    assert "users:write" in profile["permissions"]
    assert "routes:manage" in profile["permissions"]
    assert profile["rls_enforced_tenant"] == 0


@pytest.mark.asyncio
async def test_authorization_standard_user(service: AuthorizationService):
    tenant_repo: FakeTenantRepository = service.tenant_repo
    tenant_repo.flags[1] = {"allow_private_as2": False}

    token_payload = {"urn:zitadel:iam:org:project:roles": {}}

    profile = await service.get_authorization_profile(
        tenant_id=1, token_payload=token_payload, current_rls_tenant=1
    )

    assert profile["status"] == "success"
    assert profile["tenant_id"] == 1
    assert profile["is_platform_admin"] is False
    assert profile["allow_private_as2"] is False
    assert profile["role"] == "Standard"
    assert "users:read" in profile["permissions"]
    assert "users:write" not in profile["permissions"]
    assert profile["rls_enforced_tenant"] == 1


def test_authorization_platform_admin_by_tenant_id():
    import asyncio

    repo = FakeTenantRepository()
    svc = AuthorizationService(repo)
    profile = asyncio.run(svc.get_authorization_profile(0, {}, None))
    # tenant_id == 0 no longer grants platform admin
    assert profile["is_platform_admin"] is False
    assert profile["role"] == "Standard"
