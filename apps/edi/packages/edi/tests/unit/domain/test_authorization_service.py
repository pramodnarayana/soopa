"""
Pure Domain & Application Unit Tests: AuthorizationPolicy and GetAuthorizationProfileUseCase.

AuthorizationPolicy is 100% pure synchronous domain logic (zero ports, zero fakes).
GetAuthorizationProfileUseCase orchestrates TenantRepositoryPort and delegates to AuthorizationPolicy.
"""

from __future__ import annotations

import pytest
from seedwork.utils import generate_id

from edi.application.use_cases.authorization.get_authorization_profile_use_case import (
    GetAuthorizationProfileQuery,
    GetAuthorizationProfileUseCase,
)
from edi.domain.authorization import (
    AuthorizationPolicy,
    EdiAuthorizationRole,
    EdiPermission,
    TenantFeatureFlags,
)
from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.types import JsonDict
from edi.testing.fakes.api_fakes import FakeTenantRepository


class TestAuthorizationPolicyPureDomain:
    def setup_method(self) -> None:
        self.tenant_id = generate_id(DomainIdPrefix.TENANT)

    def _evaluate(
        self,
        *,
        tenant_id: str | None = None,
        is_platform_admin: bool = False,
        current_rls_tenant: str | None = None,
        roles: list[str] | None = None,
        tenant_flags: TenantFeatureFlags | None = None,
    ) -> JsonDict:
        resolved_tenant = tenant_id or self.tenant_id
        profile = AuthorizationPolicy.evaluate(
            tenant_id=resolved_tenant,
            is_platform_admin=is_platform_admin,
            current_rls_tenant=current_rls_tenant,
            roles=roles,
            tenant_flags=tenant_flags,
        )
        return profile.to_dict()

    def test_platform_admin_gets_owner_role(self) -> None:
        profile = self._evaluate(is_platform_admin=True)
        assert profile["role"] == EdiAuthorizationRole.OWNER.value

    def test_platform_admin_gets_full_permissions(self) -> None:
        profile = self._evaluate(is_platform_admin=True)
        permissions = profile["permissions"]
        assert isinstance(permissions, list)
        assert EdiPermission.CERTIFICATES_EXPORT_PRIVATE.value in permissions
        assert EdiPermission.CERTIFICATES_ROTATE.value in permissions
        assert EdiPermission.ROUTES_MANAGE.value in permissions

    def test_owner_role_in_roles_list_grants_admin_role(self) -> None:
        profile = self._evaluate(roles=["owner"])
        assert profile["role"] == EdiAuthorizationRole.ADMIN.value

    def test_admin_role_in_roles_list_grants_admin_role(self) -> None:
        profile = self._evaluate(roles=["admin"])
        assert profile["role"] == EdiAuthorizationRole.ADMIN.value

    def test_admin_role_is_case_insensitive(self) -> None:
        profile = self._evaluate(roles=["ADMIN"])
        assert profile["role"] == EdiAuthorizationRole.ADMIN.value

    def test_admin_gets_management_permissions(self) -> None:
        profile = self._evaluate(roles=["admin"])
        permissions = profile["permissions"]
        assert isinstance(permissions, list)
        assert EdiPermission.USERS_WRITE.value in permissions
        assert EdiPermission.USERS_DELETE.value in permissions

    def test_standard_user_gets_standard_role(self) -> None:
        profile = self._evaluate(roles=["member"])
        assert profile["role"] == EdiAuthorizationRole.STANDARD.value

    def test_standard_user_gets_only_read_permission(self) -> None:
        profile = self._evaluate(roles=["member"])
        assert profile["permissions"] == [EdiPermission.USERS_READ.value]

    def test_no_roles_returns_standard(self) -> None:
        profile = self._evaluate(roles=[])
        assert profile["role"] == EdiAuthorizationRole.STANDARD.value

    def test_none_roles_defaults_to_standard(self) -> None:
        profile = self._evaluate(roles=None)
        assert profile["role"] == EdiAuthorizationRole.STANDARD.value

    def test_platform_admin_overrides_roles(self) -> None:
        profile = self._evaluate(is_platform_admin=True, roles=[])
        assert profile["role"] == EdiAuthorizationRole.OWNER.value

    def test_profile_contains_tenant_id(self) -> None:
        t_id = generate_id(DomainIdPrefix.TENANT)
        profile = self._evaluate(tenant_id=t_id)
        assert profile["tenant_id"] == t_id

    def test_profile_contains_rls_enforced_tenant(self) -> None:
        rls_id = generate_id(DomainIdPrefix.TENANT)
        profile = self._evaluate(current_rls_tenant=rls_id)
        assert profile["rls_enforced_tenant"] == rls_id

    def test_profile_status_is_success(self) -> None:
        profile = self._evaluate()
        assert profile["status"] == "success"


class TestGetAuthorizationProfileUseCase:
    @pytest.mark.asyncio
    async def test_allow_private_as2_flag_is_false_by_default(self) -> None:
        repo = FakeTenantRepository()
        use_case = GetAuthorizationProfileUseCase(tenant_repo=repo)
        tenant_id = generate_id(DomainIdPrefix.TENANT)
        profile = await use_case.execute(
            GetAuthorizationProfileQuery(
                tenant_id=tenant_id,
                is_platform_admin=False,
                current_rls_tenant=None,
            )
        )
        assert profile.allow_private_as2 is False

    @pytest.mark.asyncio
    async def test_allow_private_as2_flag_is_read_from_tenant_flags(self) -> None:
        repo = FakeTenantRepository()
        tenant_id = generate_id(DomainIdPrefix.TENANT)
        repo.flags[tenant_id] = TenantFeatureFlags(allow_private_as2=True)
        use_case = GetAuthorizationProfileUseCase(tenant_repo=repo)
        profile = await use_case.execute(
            GetAuthorizationProfileQuery(
                tenant_id=tenant_id,
                is_platform_admin=False,
                current_rls_tenant=None,
            )
        )
        assert profile.allow_private_as2 is True

    @pytest.mark.asyncio
    async def test_no_tenant_flags_does_not_raise(self) -> None:
        repo = FakeTenantRepository()
        use_case = GetAuthorizationProfileUseCase(tenant_repo=repo)
        profile = await use_case.execute(
            GetAuthorizationProfileQuery(
                tenant_id="unknown_tenant",
                is_platform_admin=False,
                current_rls_tenant=None,
            )
        )
        assert profile.allow_private_as2 is False
