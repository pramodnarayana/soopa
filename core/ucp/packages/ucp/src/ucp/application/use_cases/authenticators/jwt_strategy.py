from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import structlog
from identity.application.authenticate_use_case import (
    TenantNotProvisionedError,
    authenticate_bearer_token,
)
from identity.domain.authentication_strategy import AuthenticationStrategyPort
from identity.domain.identity_context import IdentityContext
from identity.ports.outbound.token_verifier_port import TokenVerifierPort

from ucp.domain.models.authorization import Capability
from ucp.ports.outbound.role_repository_port import RoleRepositoryPort
from ucp.ports.outbound.tenant_repository_port import TenantRepositoryPort
from ucp.ports.outbound.user_repository_port import UserRepositoryPort

logger = structlog.get_logger(__name__)


class JwtStrategy(AuthenticationStrategyPort):
    """
    Authentication strategy for standard Identity Provider (IdP) JWT tokens.
    """

    def __init__(
        self,
        tenant_repo_factory: Callable[[], AbstractAsyncContextManager[TenantRepositoryPort]],
        user_repo_factory: Callable[[], AbstractAsyncContextManager[UserRepositoryPort]],
        role_repo_factory: Callable[[], AbstractAsyncContextManager[RoleRepositoryPort]],
        token_verifier: TokenVerifierPort,
    ):
        self.tenant_repo_factory = tenant_repo_factory
        self.user_repo_factory = user_repo_factory
        self.role_repo_factory = role_repo_factory
        self.token_verifier = token_verifier

    def can_handle(self, token: str) -> bool:
        # JWTs don't have a reliable prefix, so this acts as the default fallback
        # strategy if no other strategy claims the token.
        return True

    async def authenticate(self, token: str) -> IdentityContext:  # noqa: C901
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

        # Map IdP user ID to Canonical UCP user ID
        if identity.subject and not identity.subject.startswith("usr_"):
            async with self.user_repo_factory() as user_repo:
                resolved_u = await user_repo.find_by_idp_user_id(identity.subject)
                if resolved_u:
                    identity.subject = resolved_u.id

        # Backwards compatibility: if Zitadel token claims they are "admin", grant legacy capabilities
        if identity.is_platform_admin:
            identity.capabilities.add(Capability.PLATFORM_ADMIN.value)
        # Note: Tenant-scoped admin grants from roles are now resolved via database roles only
        # to prevent cross-tenant privilege escalation

        # 3. Resolve Dynamic Postgres PBAC Capabilities
        async with self.role_repo_factory() as role_repo:
            # Resolve platform-wide capabilities (where tenant_id is NULL)
            platform_capabilities = await role_repo.get_user_capabilities(
                tenant_id=None,  # None represents platform-wide roles
                user_id=identity.subject,
            )
            identity.capabilities.update(platform_capabilities)

            # Resolve tenant-specific capabilities if tenant is set
            if identity.tenant_id:
                db_capabilities = await role_repo.get_user_capabilities(
                    tenant_id=identity.tenant_id, user_id=identity.subject
                )
                identity.capabilities.update(db_capabilities)

        return identity
