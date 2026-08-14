from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import structlog
from identity.application.authenticate import TenantNotProvisionedError, authenticate_bearer_token
from identity.domain.authentication_strategy import IAuthenticationStrategy
from identity.domain.identity_context import IdentityContext
from identity.ports.token_verifier import TokenVerifier

from ucp.domain.models.authorization import Capability
from ucp.ports.outbound.role_repository import IRoleRepository
from ucp.ports.outbound.tenant_repository import ITenantRepository

logger = structlog.get_logger(__name__)


class JwtStrategy(IAuthenticationStrategy):
    """
    Authentication strategy for standard Identity Provider (IdP) JWT tokens.
    """

    def __init__(
        self,
        tenant_repo_factory: Callable[[], AbstractAsyncContextManager[ITenantRepository]],
        role_repo_factory: Callable[[], AbstractAsyncContextManager[IRoleRepository]],
        token_verifier: TokenVerifier,
    ):
        self.tenant_repo_factory = tenant_repo_factory
        self.role_repo_factory = role_repo_factory
        self.token_verifier = token_verifier

    def can_handle(self, token: str) -> bool:
        # JWTs don't have a reliable prefix, so this acts as the default fallback
        # strategy if no other strategy claims the token.
        return True

    async def authenticate(self, token: str) -> IdentityContext:
        # Note: We let AuthenticationError propagate up so the caller handles it
        identity: IdentityContext = await authenticate_bearer_token(
            f"Bearer {token}", self.token_verifier
        )

        # Map IdP tenant ID to Canonical UCP tenant ID exactly once at the perimeter.
        async with self.tenant_repo_factory() as repo:
            # 1. Map the primary tenant_id if present
            if identity.tenant_id and not identity.tenant_id.startswith("ten_"):
                resolved = await repo.find_by_idp_tenant_id(identity.tenant_id)
                if resolved:
                    identity.tenant_id = resolved.id
                    identity.authorized_tenants.add(resolved.id)

            # 2. Map all authorized tenants that are IdP IDs
            mapped_tenants = set()
            for tid in identity.authorized_tenants:
                if not tid.startswith("ten_") and tid != "ten_000000000000000000000000":
                    resolved_t = await repo.find_by_idp_tenant_id(tid)
                    if resolved_t:
                        mapped_tenants.add(resolved_t.id)
                        mapped_tenants.add(
                            tid
                        )  # MUST keep original IdP ID so guard can match it if requested!
                        identity.tenant_mapping[tid] = resolved_t.id
                        # Default primary tenant if missing
                        if not identity.tenant_id:
                            identity.tenant_id = resolved_t.id
                    else:
                        logger.error(
                            "CRITICAL: IdP Tenant ID '%s' found in token but NOT found in local database!",
                            tid,
                        )
                        raise TenantNotProvisionedError(tid)
                else:
                    mapped_tenants.add(tid)

            identity.authorized_tenants = mapped_tenants

        # Backwards compatibility: if Zitadel token claims they are "admin", grant legacy capabilities
        if identity.is_platform_admin:
            identity.capabilities.add(Capability.PLATFORM_ADMIN.value)
        elif identity.roles and any(r.lower() in ("admin", "tenantadmin") for r in identity.roles):
            identity.capabilities.add(Capability.TENANT_ADMIN.value)

        # 3. Resolve Dynamic Postgres PBAC Capabilities
        if identity.tenant_id:
            async with self.role_repo_factory() as role_repo:
                db_capabilities = await role_repo.get_user_capabilities(
                    tenant_id=identity.tenant_id, user_id=identity.subject
                )
                identity.capabilities.update(db_capabilities)

                # Also resolve platform-wide capabilities (where tenant_id is NULL)
                platform_capabilities = await role_repo.get_user_capabilities(
                    tenant_id=None,  # None represents platform-wide roles
                    user_id=identity.subject,
                )
                identity.capabilities.update(platform_capabilities)

        return identity
