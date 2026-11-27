from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from datetime import UTC, datetime

import structlog
from identity.application.authenticate_use_case import (
    AuthenticateCommand,
    AuthenticationError,
    TenantNotProvisionedError,
    authenticate_bearer_token,
)
from identity.domain.authentication_strategy import AuthenticationStrategyPort
from identity.domain.constants import MembershipStatus, UserStatus
from identity.domain.dtos import PrincipalSnapshotDTO
from identity.domain.identity_context import PLATFORM_TENANT_ID, IdentityContext
from identity.ports.outbound.external_identity_repository_port import (
    ExternalIdentityRepositoryPort,
)
from identity.ports.outbound.principal_cache_port import PrincipalCachePort
from identity.ports.outbound.role_repository_port import RoleRepositoryPort
from identity.ports.outbound.tenant_hierarchy_port import (
    AuthzDirectoryPort,
    GlobalAuthzCatalogPort,
)
from identity.ports.outbound.token_verifier_port import TokenVerifierPort
from identity.ports.outbound.user_repository_port import UserRepositoryPort

from ucp.ports.outbound.tenant_repository_port import TenantRepositoryPort

logger = structlog.get_logger(__name__)


class JwtStrategy(AuthenticationStrategyPort):
    """
    IdP-agnostic OIDC JWT Authentication Strategy.

    1. Verifies standard OIDC JWT signature, issuer, audience/azp, and expiration via `TokenVerifierPort`.
    2. Resolves `(idp_issuer, idp_subject) -> canonical user_id` via `identity.external_identities`
       (with legacy `idp_user_id` fallback).
    3. Checks bounded L1 LRU `PrincipalCachePort` + `GlobalAuthzCatalogPort` for zero-DB membership,
       `tokens_valid_after` revocation, and capability resolution (falling back to DB only on miss).
    """

    def __init__(
        self,
        tenant_repo_factory: Callable[[], AbstractAsyncContextManager[TenantRepositoryPort]],
        user_repo_factory: Callable[[], AbstractAsyncContextManager[UserRepositoryPort]],
        role_repo_factory: Callable[[], AbstractAsyncContextManager[RoleRepositoryPort]],
        token_verifier: TokenVerifierPort,
        *,
        external_identity_repo_factory: (
            Callable[[], AbstractAsyncContextManager[ExternalIdentityRepositoryPort]] | None
        ) = None,
        authz_directory_repo_factory: (
            Callable[[], AbstractAsyncContextManager[AuthzDirectoryPort]] | None
        ) = None,
        principal_cache: PrincipalCachePort | None = None,
        global_catalog: GlobalAuthzCatalogPort | None = None,
    ):
        self.tenant_repo_factory = tenant_repo_factory
        self.user_repo_factory = user_repo_factory
        self.role_repo_factory = role_repo_factory
        self.token_verifier = token_verifier
        self._external_identity_repo_factory = external_identity_repo_factory
        self._authz_directory_repo_factory = authz_directory_repo_factory
        self._principal_cache = principal_cache
        self._global_catalog = global_catalog

    def can_handle(self, token: str) -> bool:
        return True

    async def authenticate(self, token: str) -> IdentityContext:
        command = AuthenticateCommand(authorization_header=f"Bearer {token}")
        identity: IdentityContext = await authenticate_bearer_token(command, self.token_verifier)

        subject = await self._resolve_canonical_user_id(identity)
        tenant_id, authorized_tenants, snapshot = await self._resolve_from_principal_snapshot(
            identity, subject
        )

        if snapshot is None or (tenant_id and not tenant_id.startswith(("ten_", "iam_ten_"))):
            async with self.tenant_repo_factory() as repo:
                mapped_primary, mapped_set = await self._resolve_tenant_mappings(repo, identity)
                authorized_tenants.update(mapped_set)
                if mapped_primary:
                    tenant_id = mapped_primary

        if not tenant_id and PLATFORM_TENANT_ID in authorized_tenants:
            tenant_id = PLATFORM_TENANT_ID

        identity = replace(
            identity,
            subject=subject,
            tenant_id=tenant_id,
            authorized_tenants=authorized_tenants,
        )
        if not await self._try_populate_cached_capabilities(identity, snapshot):
            await self._populate_capabilities_from_db(identity)
        return identity

    async def _resolve_from_principal_snapshot(
        self,
        identity: IdentityContext,
        subject: str,
    ) -> tuple[str | None, set[str], PrincipalSnapshotDTO | None]:
        tenant_id = identity.tenant_id
        authorized_tenants = set(identity.authorized_tenants)
        if not subject.startswith(("iam_usr_", "usr_")) or self._principal_cache is None:
            return tenant_id, authorized_tenants, None

        snapshot = await self._principal_cache.get_principal(subject)
        if snapshot is None and self._authz_directory_repo_factory is not None:
            async with self._authz_directory_repo_factory() as directory:
                snapshot = await directory.get_principal_snapshot(user_id=subject)
            if snapshot is not None:
                await self._principal_cache.set_principal(snapshot)

        if snapshot is None:
            return tenant_id, authorized_tenants, None

        self._enforce_snapshot_revocation(
            identity,
            snapshot.tokens_valid_after,
            snapshot.status == UserStatus.ACTIVE,
        )
        for membership in snapshot.memberships:
            if membership.status == MembershipStatus.ACTIVE:
                authorized_tenants.add(membership.tenant_id)
        if not tenant_id and PLATFORM_TENANT_ID in authorized_tenants:
            tenant_id = PLATFORM_TENANT_ID
        elif not tenant_id and len(authorized_tenants) == 1:
            tenant_id = next(iter(authorized_tenants))
        return tenant_id, authorized_tenants, snapshot

    async def _try_populate_cached_capabilities(
        self,
        identity: IdentityContext,
        snapshot: PrincipalSnapshotDTO | None,
    ) -> bool:
        """Resolve capabilities purely from L1 RAM cache / Global Catalog (0 DB queries on hit)."""
        if snapshot is None or self._principal_cache is None:
            return False
        now = datetime.now(UTC)
        relevant_tenants = {PLATFORM_TENANT_ID}
        if identity.tenant_id:
            relevant_tenants.add(identity.tenant_id)

        role_ids = [
            ra.role_id
            for ra in snapshot.role_assignments
            if ra.tenant_id in relevant_tenants and (ra.expires_at is None or ra.expires_at > now)
        ]
        if not role_ids:
            return True

        allow_caps: set[str] = set()
        deny_caps: set[str] = set()
        for role_id in role_ids:
            role_def = (
                self._global_catalog.get_platform_role(role_id)
                if self._global_catalog is not None
                else None
            )
            if role_def is None:
                role_def = await self._principal_cache.get_role_definition(role_id)
            if role_def is None:
                return False
            allow_caps.update(role_def.capabilities)
            deny_caps.update(role_def.deny_capabilities)

        identity.capabilities.update(allow_caps - deny_caps)
        return True

    async def _populate_capabilities_from_db(self, identity: IdentityContext) -> None:
        async with self.role_repo_factory() as role_repo:
            platform_capabilities = await role_repo.get_user_capabilities(
                tenant_id=None,
                user_id=identity.subject,
            )
            identity.capabilities.update(platform_capabilities)

            if identity.tenant_id:
                db_capabilities = await role_repo.get_user_capabilities(
                    tenant_id=identity.tenant_id, user_id=identity.subject
                )
                identity.capabilities.update(db_capabilities)

    async def _resolve_canonical_user_id(self, identity: IdentityContext) -> str:
        subject = identity.subject
        if not subject or subject.startswith("iam_usr_"):
            return subject

        issuer_raw = identity.claims.get("iss")
        issuer = issuer_raw.strip().rstrip("/") if isinstance(issuer_raw, str) else ""

        if issuer and self._external_identity_repo_factory is not None:
            async with self._external_identity_repo_factory() as ext_repo:
                ext = await ext_repo.find_by_issuer_subject(
                    idp_issuer=issuer,
                    idp_subject=subject,
                )
                if ext is not None:
                    return ext.user_id

        async with self.user_repo_factory() as user_repo:
            resolved_u = await user_repo.find_by_idp_user_id(subject)
            if resolved_u:
                return resolved_u.id
        return subject

    @staticmethod
    def _enforce_snapshot_revocation(
        identity: IdentityContext,
        tokens_valid_after: datetime | None,
        is_active: bool,
    ) -> None:
        if not is_active:
            logger.error("jwt_auth_rejected_user_inactive", user_id=identity.subject)
            raise AuthenticationError("User account is inactive.")
        if tokens_valid_after is None:
            return
        iat_raw = identity.claims.get("iat")
        if isinstance(iat_raw, int):
            token_iat = datetime.fromtimestamp(iat_raw, tz=UTC)
            cutoff = (
                tokens_valid_after
                if tokens_valid_after.tzinfo is not None
                else tokens_valid_after.replace(tzinfo=UTC)
            )
            if token_iat < cutoff:
                logger.error(
                    "jwt_auth_rejected_token_revoked",
                    user_id=identity.subject,
                    token_iat=token_iat.isoformat(),
                    tokens_valid_after=cutoff.isoformat(),
                )
                raise AuthenticationError("Token has been revoked.")

    async def _map_idp_tenant(
        self, repo: TenantRepositoryPort, identity: IdentityContext, tid: str
    ) -> str:
        if tid in identity.tenant_mapping:
            return identity.tenant_mapping[tid]
        resolved = await repo.find_by_idp_realm(tid)
        if not resolved:
            logger.error("tenant_idp_mapping_failed_unprovisioned", idp_realm_name=tid)
            raise TenantNotProvisionedError(tid)
        identity.tenant_mapping[tid] = resolved.id
        return resolved.id

    async def _resolve_tenant_mappings(
        self, repo: TenantRepositoryPort, identity: IdentityContext
    ) -> tuple[str | None, set[str]]:
        tenant_id = identity.tenant_id

        if tenant_id and not tenant_id.startswith("ten_") and not tenant_id.startswith("iam_ten_"):
            canonical_primary = await self._map_idp_tenant(repo, identity, tenant_id)
            tenant_id = canonical_primary
            identity.authorized_tenants.add(canonical_primary)

        mapped_tenants: set[str] = set()
        for tid in identity.authorized_tenants:
            if not tid.startswith("iam_ten_") and not tid.startswith("ten_"):
                canonical_id = await self._map_idp_tenant(repo, identity, tid)
                mapped_tenants.add(canonical_id)
                mapped_tenants.add(tid)
                if not tenant_id:
                    tenant_id = canonical_id
            else:
                mapped_tenants.add(tid)
                if not tenant_id:
                    tenant_id = tid

        if not tenant_id and PLATFORM_TENANT_ID in mapped_tenants:
            tenant_id = PLATFORM_TENANT_ID

        return tenant_id, mapped_tenants
