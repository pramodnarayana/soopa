"""
Layer 1 — Pure Domain Unit Tests: AuthorizationService.

AuthorizationService is a pure domain service that depends on TenantRepositoryPort.
We inject a simple in-memory fake — no mocks, no SQLAlchemy.
"""

import pytest
from identity.domain.constants import IdentityIdPrefix
from seedwork.utils import generate_id

from edi.domain.authorization import AuthorizationService
from edi.testing.fakes.api_fakes import FakeTenantRepository


class TestAuthorizationServiceRoleResolution:
    def setup_method(self):
        self.tenant_repo = FakeTenantRepository()
        self.svc = AuthorizationService(tenant_repo=self.tenant_repo)
        self.tenant_id = generate_id(IdentityIdPrefix.TENANT)

    async def _get_profile(
        self,
        tenant_id=None,
        is_platform_admin=False,
        current_rls_tenant=None,
        roles=None,
    ):
        tenant_id = tenant_id or self.tenant_id
        return await self.svc.get_authorization_profile(
            tenant_id=tenant_id,
            is_platform_admin=is_platform_admin,
            current_rls_tenant=current_rls_tenant,
            roles=roles or [],
        )

    @pytest.mark.asyncio
    async def test_platform_admin_gets_owner_role(self):
        profile = await self._get_profile(is_platform_admin=True)
        assert profile["role"] == "Owner"

    @pytest.mark.asyncio
    async def test_platform_admin_gets_full_permissions(self):
        profile = await self._get_profile(is_platform_admin=True)
        assert "certificates:export_private" in profile["permissions"]
        assert "certificates:rotate" in profile["permissions"]
        assert "routes:manage" in profile["permissions"]

    @pytest.mark.asyncio
    async def test_owner_role_in_roles_list_grants_admin_role(self):
        profile = await self._get_profile(roles=["owner"])
        assert profile["role"] == "Admin"

    @pytest.mark.asyncio
    async def test_admin_role_in_roles_list_grants_admin_role(self):
        profile = await self._get_profile(roles=["admin"])
        assert profile["role"] == "Admin"

    @pytest.mark.asyncio
    async def test_admin_role_is_case_insensitive(self):
        profile = await self._get_profile(roles=["ADMIN"])
        assert profile["role"] == "Admin"

    @pytest.mark.asyncio
    async def test_admin_gets_management_permissions(self):
        profile = await self._get_profile(roles=["admin"])
        assert "users:write" in profile["permissions"]
        assert "users:delete" in profile["permissions"]

    @pytest.mark.asyncio
    async def test_standard_user_gets_standard_role(self):
        profile = await self._get_profile(roles=["member"])
        assert profile["role"] == "Standard"

    @pytest.mark.asyncio
    async def test_standard_user_gets_only_read_permission(self):
        profile = await self._get_profile(roles=["member"])
        assert profile["permissions"] == ["users:read"]

    @pytest.mark.asyncio
    async def test_no_roles_returns_standard(self):
        profile = await self._get_profile(roles=[])
        assert profile["role"] == "Standard"

    @pytest.mark.asyncio
    async def test_none_roles_defaults_to_standard(self):
        profile = await self._get_profile(roles=None)
        assert profile["role"] == "Standard"

    @pytest.mark.asyncio
    async def test_platform_admin_overrides_roles(self):
        """Even with no roles, platform admin must always get Owner."""
        profile = await self._get_profile(is_platform_admin=True, roles=[])
        assert profile["role"] == "Owner"

    @pytest.mark.asyncio
    async def test_profile_contains_tenant_id(self):
        t_id = generate_id(IdentityIdPrefix.TENANT)
        profile = await self._get_profile(tenant_id=t_id)
        assert profile["tenant_id"] == t_id

    @pytest.mark.asyncio
    async def test_profile_contains_rls_enforced_tenant(self):
        rls_id = generate_id(IdentityIdPrefix.TENANT)
        profile = await self._get_profile(current_rls_tenant=rls_id)
        assert profile["rls_enforced_tenant"] == rls_id

    @pytest.mark.asyncio
    async def test_profile_status_is_success(self):
        profile = await self._get_profile()
        assert profile["status"] == "success"


class TestAuthorizationServiceFeatureFlags:
    @pytest.mark.asyncio
    async def test_allow_private_as2_flag_is_false_by_default(self):
        repo = FakeTenantRepository()
        svc = AuthorizationService(tenant_repo=repo)
        tenant_id = generate_id(IdentityIdPrefix.TENANT)
        profile = await svc.get_authorization_profile(
            tenant_id=tenant_id, is_platform_admin=False, current_rls_tenant=None
        )
        assert profile["allow_private_as2"] is False

    @pytest.mark.asyncio
    async def test_allow_private_as2_flag_is_read_from_tenant_flags(self):
        repo = FakeTenantRepository()
        tenant_id = generate_id(IdentityIdPrefix.TENANT)
        repo.flags[tenant_id] = {"allow_private_as2": True}
        svc = AuthorizationService(tenant_repo=repo)
        profile = await svc.get_authorization_profile(
            tenant_id=tenant_id, is_platform_admin=False, current_rls_tenant=None
        )
        assert profile["allow_private_as2"] is True

    @pytest.mark.asyncio
    async def test_no_tenant_flags_does_not_raise(self):
        repo = FakeTenantRepository()
        # flags dict is empty — get_tenant_flags returns None
        svc = AuthorizationService(tenant_repo=repo)
        profile = await svc.get_authorization_profile(
            tenant_id="unknown_tenant", is_platform_admin=False, current_rls_tenant=None
        )
        assert profile["allow_private_as2"] is False
