"""Application use case for resolving a caller's EDI authorization profile."""

from __future__ import annotations

from dataclasses import dataclass

from edi.domain.authorization.service import AuthorizationPolicy, AuthorizationProfile
from edi.ports.outbound.tenant_repository import TenantRepositoryPort


@dataclass(frozen=True, kw_only=True)
class GetAuthorizationProfileQuery:
    """Co-located query DTO for resolving an EDI authorization profile."""

    tenant_id: str
    is_platform_admin: bool
    current_rls_tenant: str | None = None
    roles: tuple[str, ...] = ()


class GetAuthorizationProfileUseCase:
    """Loads tenant feature flags via port and delegates RBAC evaluation to AuthorizationPolicy."""

    def __init__(self, tenant_repo: TenantRepositoryPort) -> None:
        self.tenant_repo = tenant_repo

    async def execute(self, query: GetAuthorizationProfileQuery) -> AuthorizationProfile:
        tenant_flags = await self.tenant_repo.get_tenant_flags(query.tenant_id)
        return AuthorizationPolicy.evaluate(
            tenant_id=query.tenant_id,
            is_platform_admin=query.is_platform_admin,
            current_rls_tenant=query.current_rls_tenant,
            roles=query.roles,
            tenant_flags=tenant_flags,
        )


__all__ = [
    "GetAuthorizationProfileQuery",
    "GetAuthorizationProfileUseCase",
]
