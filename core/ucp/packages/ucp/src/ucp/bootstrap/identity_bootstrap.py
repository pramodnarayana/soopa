"""IdP-agnostic platform control-plane bootstrap and tenant cleanup utilities."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

import structlog
from database.models.identity import ExternalIdentity, Role, Tenant, TenantUser, User, UserRole
from identity.domain.constants import (
    IdentityIdPrefix,
    MembershipScope,
    MembershipStatus,
    TenantIsolationMode,
)
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.domain.constants import LifecycleStatus, UcpIdPrefix

logger = structlog.get_logger(__name__)

PLATFORM_ADMIN_ROLE_NAME = "PlatformAdmin"


@dataclass(frozen=True)
class PlatformSeedConfig:
    """Canonical inputs required to bootstrap the platform control plane idempotently."""

    platform_org_id: str
    platform_admin_id: str
    platform_admin_email: str
    idp_issuer: str = ""


@dataclass(frozen=True)
class _CanonicalRoleSpec:
    role_id: str
    name: str
    description: str
    capabilities: tuple[str, ...]


_CANONICAL_PLATFORM_ROLES: tuple[_CanonicalRoleSpec, ...] = (
    _CanonicalRoleSpec(
        role_id="rol_97f48b1115b74100",
        name=PLATFORM_ADMIN_ROLE_NAME,
        description="Full access to the entire platform.",
        capabilities=("platform:admin",),
    ),
    _CanonicalRoleSpec(
        role_id="rol_a62f2225bf70bfac",
        name="TenantAdmin",
        description="Full access to manage a specific tenant.",
        capabilities=(
            "tenant:admin",
            "tenant_settings:read",
            "tenant_settings:write",
            "users:read",
            "users:write",
            "roles:read",
            "roles:write",
            "api_keys:read",
            "api_keys:write",
            "webhooks:read",
            "webhooks:write",
            "invoices:read",
            "invoices:write",
        ),
    ),
    _CanonicalRoleSpec(
        role_id="rol_1d55e88863640224",
        name="Viewer",
        description="Read-only access to a specific tenant.",
        capabilities=(
            "tenant_settings:read",
            "users:read",
            "roles:read",
            "api_keys:read",
            "webhooks:read",
            "invoices:read",
        ),
    ),
)


async def purge_non_platform_tenants(
    *,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    batch_size: int = 100,
    yield_seconds: float = 0.1,
) -> int:
    """Delete non-platform tenants in bounded chunks without touching PLATFORM_TENANT_ID or its roles."""
    total_deleted = 0
    while True:
        async with session_factory() as session:
            batch_ids = list(
                (
                    await session.execute(
                        select(Tenant.id)
                        .where(Tenant.id != PLATFORM_TENANT_ID)
                        .order_by(Tenant.id)
                        .limit(batch_size)
                    )
                )
                .scalars()
                .all()
            )
            if not batch_ids:
                break

            await session.execute(delete(Tenant).where(Tenant.id.in_(batch_ids)))
            await session.commit()
            total_deleted += len(batch_ids)

        if yield_seconds > 0:
            await asyncio.sleep(yield_seconds)

    logger.info("non_platform_tenants_purged", deleted_count=total_deleted)
    return total_deleted


async def _seed_platform_tenant(session: AsyncSession, platform_org_id: str) -> None:
    await session.execute(
        update(Tenant)
        .where(
            Tenant.id != PLATFORM_TENANT_ID,
            Tenant.isolation_mode == TenantIsolationMode.DEDICATED_IDP_ORG.value,
            Tenant.idp_realm_name == platform_org_id,
        )
        .values(idp_realm_name=None)
    )

    stmt_tenant = (
        pg_insert(Tenant)
        .values(
            id=PLATFORM_TENANT_ID,
            name="Platform Organization",
            slug="platform",
            isolation_mode=TenantIsolationMode.DEDICATED_IDP_ORG.value,
            idp_realm_name=platform_org_id,
            status=LifecycleStatus.ACTIVE.value,
            deleted_at=None,
            deleted_by=None,
        )
        .on_conflict_do_update(
            index_elements=[Tenant.id],
            set_={
                "name": "Platform Organization",
                "slug": "platform",
                "isolation_mode": TenantIsolationMode.DEDICATED_IDP_ORG.value,
                "idp_realm_name": platform_org_id,
                "status": LifecycleStatus.ACTIVE.value,
                "deleted_at": None,
                "deleted_by": None,
            },
        )
    )
    await session.execute(stmt_tenant)
    logger.info(
        "platform_sentinel_tenant_seeded",
        tenant_id=PLATFORM_TENANT_ID,
        platform_org_id=platform_org_id,
    )


async def _seed_platform_roles(session: AsyncSession) -> str:
    platform_admin_role_id = ""
    for spec in _CANONICAL_PLATFORM_ROLES:
        stmt_role = (
            pg_insert(Role)
            .values(
                id=spec.role_id,
                tenant_id=PLATFORM_TENANT_ID,
                name=spec.name,
                description=spec.description,
                capabilities=list(spec.capabilities),
                deleted_at=None,
                deleted_by=None,
            )
            .on_conflict_do_update(
                index_elements=[Role.tenant_id, Role.name],
                set_={
                    "description": spec.description,
                    "capabilities": list(spec.capabilities),
                    "deleted_at": None,
                    "deleted_by": None,
                },
            )
            .returning(Role.id)
        )
        role_id = (await session.execute(stmt_role)).scalar_one()
        if spec.name == PLATFORM_ADMIN_ROLE_NAME:
            platform_admin_role_id = str(role_id)

    return platform_admin_role_id


async def _seed_platform_admin(
    session: AsyncSession,
    platform_admin_id: str,
    platform_admin_role_id: str,
    platform_admin_email: str,
    *,
    platform_org_id: str = "",
    idp_issuer: str = "",
) -> None:
    digest = hashlib.sha256(platform_admin_id.encode()).hexdigest()[:16]
    platform_user_id = f"{UcpIdPrefix.USER.value}_{digest}"
    user_role_id = f"{UcpIdPrefix.USER_ROLE.value}_{digest}"
    ext_identity_id = f"{IdentityIdPrefix.EXTERNAL_IDENTITY.value}_{digest}"
    clean_email = platform_admin_email.strip().lower()

    await session.execute(
        update(User)
        .where(
            func.lower(User.email) == clean_email,
            or_(User.idp_user_id != platform_admin_id, User.idp_user_id.is_(None)),
        )
        .values(idp_user_id=platform_admin_id, deleted_at=None, deleted_by=None)
    )

    stmt_user = (
        pg_insert(User)
        .values(
            id=platform_user_id,
            idp_user_id=platform_admin_id,
            email=clean_email,
            name="Platform Admin",
            status=LifecycleStatus.ACTIVE.value,
            deleted_at=None,
            deleted_by=None,
        )
        .on_conflict_do_update(
            index_elements=[User.idp_user_id],
            set_={
                "email": clean_email,
                "name": "Platform Admin",
                "status": LifecycleStatus.ACTIVE.value,
                "deleted_at": None,
                "deleted_by": None,
            },
        )
        .returning(User.id)
    )
    actual_user_id = str((await session.execute(stmt_user)).scalar_one())

    stmt_membership = (
        pg_insert(TenantUser)
        .values(
            user_id=actual_user_id,
            tenant_id=PLATFORM_TENANT_ID,
            scope=MembershipScope.SUBTREE.value,
            status=MembershipStatus.ACTIVE.value,
            active=True,
        )
        .on_conflict_do_update(
            index_elements=[TenantUser.user_id, TenantUser.tenant_id],
            set_={
                "scope": MembershipScope.SUBTREE.value,
                "status": MembershipStatus.ACTIVE.value,
                "active": True,
            },
        )
    )
    await session.execute(stmt_membership)

    clean_issuer = idp_issuer.strip().rstrip("/")
    if clean_issuer:
        # Remove any stale subject link for this user + issuer (e.g. after IdP reset)
        await session.execute(
            delete(ExternalIdentity).where(
                ExternalIdentity.user_id == actual_user_id,
                ExternalIdentity.idp_issuer == clean_issuer,
                ExternalIdentity.idp_subject != platform_admin_id,
            )
        )
        stmt_ext = (
            pg_insert(ExternalIdentity)
            .values(
                id=ext_identity_id,
                user_id=actual_user_id,
                idp_issuer=clean_issuer,
                idp_subject=platform_admin_id,
                idp_realm_name=platform_org_id or None,
            )
            .on_conflict_do_update(
                index_elements=[ExternalIdentity.idp_issuer, ExternalIdentity.idp_subject],
                set_={
                    "user_id": actual_user_id,
                    "idp_realm_name": platform_org_id or None,
                },
            )
        )
        await session.execute(stmt_ext)

    stmt_user_role = (
        pg_insert(UserRole)
        .values(
            id=user_role_id,
            tenant_id=PLATFORM_TENANT_ID,
            user_id=actual_user_id,
            role_id=platform_admin_role_id,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "user_id", "role_id"])
    )
    await session.execute(stmt_user_role)
    logger.info(
        "platform_admin_user_seeded",
        user_id=actual_user_id,
        platform_admin_id=platform_admin_id,
        email=clean_email,
    )


async def seed_platform_bootstrap(
    *,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    config: PlatformSeedConfig,
) -> None:
    """Idempotently seed sentinel tenant, canonical roles, and platform admin."""
    async with session_factory() as session:
        await _seed_platform_tenant(session, config.platform_org_id)
        platform_admin_role_id = await _seed_platform_roles(session)
        await _seed_platform_admin(
            session,
            config.platform_admin_id,
            platform_admin_role_id,
            config.platform_admin_email,
            platform_org_id=config.platform_org_id,
            idp_issuer=config.idp_issuer,
        )
        await session.commit()


__all__ = [
    "PLATFORM_ADMIN_ROLE_NAME",
    "PlatformSeedConfig",
    "purge_non_platform_tenants",
    "seed_platform_bootstrap",
]
