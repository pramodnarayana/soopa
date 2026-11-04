"""Enterprise Zitadel alignment verification, safe tenant cleanup, and self-healing platform bootstrap."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypedDict, cast

import httpx
import structlog
from database.constants import DatabaseShardStatus
from database.models.identity import Role, Tenant, User, UserRole
from identity.adapters.outbound.zitadel import ZitadelMachineAuthenticationError
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.sharding import DatabaseShard
from ucp_models.subscriptions import App

from ucp.domain.constants import LifecycleStatus, UcpIdPrefix

logger = structlog.get_logger(__name__)

IDENTITY_SYSTEM_ORG_NAME = "ZITADEL"
PLATFORM_ADMIN_ROLE_NAME = "PlatformAdmin"
DEFAULT_ADMIN_EMAIL = "admin@flowwolf.io"
LEGACY_ADMIN_EMAIL = "admin@soopa.ai"
EDI_PRIMARY_SHARD_ID = "edi_shard_1"
EDI_CORE_APP_ID = "app_edi_core"


class ZitadelOrgDict(TypedDict, total=False):
    id: str
    name: str


class AccessTokenProviderPort(Protocol):
    """Port for exchanging machine credentials for a short-lived IdP access token."""

    async def get_access_token(self) -> str: ...


class AsyncSessionFactoryPort(Protocol):
    """Callable returning an async session context manager."""

    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]: ...


class ZitadelDriftReason(StrEnum):
    """Structured failure reasons when local .env state drifts from live Zitadel."""

    MISSING_CREDENTIALS = "missing_credentials"
    UNREACHABLE = "unreachable"
    MACHINE_AUTH_FAILED = "machine_auth_failed"
    PLATFORM_ORG_MISSING = "platform_org_missing"
    PLATFORM_ADMIN_MISSING = "platform_admin_missing"
    UCP_PROJECT_MISSING = "ucp_project_missing"


@dataclass(frozen=True)
class ZitadelIdentityConfig:
    """Expected Zitadel identity coordinates read from the repository environment."""

    zitadel_url: str
    machine_key: str
    platform_org_id: str
    platform_admin_id: str
    ucp_project_id: str


@dataclass(frozen=True)
class ZitadelAlignmentResult:
    """First-class result of verifying .env identity coordinates against live Zitadel."""

    aligned: bool
    reason: ZitadelDriftReason | None = None
    detail: str | None = None
    access_token: str | None = None
    all_orgs: tuple[ZitadelOrgDict, ...] = ()


@dataclass(frozen=True)
class ShardSeedSpec:
    """Generic database shard registration record seeded at platform bootstrap."""

    shard_id: str
    name: str
    dsn: str


@dataclass(frozen=True)
class PlatformSeedConfig:
    """Canonical inputs required to bootstrap the platform control plane idempotently."""

    platform_org_id: str
    platform_admin_id: str
    edi_shard_dsn: str = ""
    edi_project_id: str = ""
    extra_shards: tuple[ShardSeedSpec, ...] = ()


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


async def wait_for_zitadel_ready(
    http_client: httpx.AsyncClient,
    zitadel_url: str,
    *,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.5,
) -> bool:
    """Poll Zitadel /debug/ready until HTTP 200 or timeout."""
    ready_url = f"{zitadel_url.rstrip('/')}/debug/ready"
    deadline = time.monotonic() + max(timeout_seconds, 0.0)

    while True:
        try:
            resp = await http_client.get(ready_url, timeout=3.0)
            if resp.status_code == 200:
                return True
        except httpx.HTTPError:
            pass

        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(poll_interval_seconds)


async def _list_all_orgs(
    http_client: httpx.AsyncClient,
    zitadel_url: str,
    access_token: str,
) -> list[ZitadelOrgDict]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    response = await http_client.post(
        f"{zitadel_url.rstrip('/')}/admin/v1/orgs/_search",
        headers=headers,
        json={"query": {"offset": "0", "limit": 500}},
        timeout=15.0,
    )
    response.raise_for_status()
    payload: object = response.json()
    if not isinstance(payload, dict):
        return []
    raw_result = payload.get("result", [])
    if not isinstance(raw_result, list):
        return []
    return cast("list[ZitadelOrgDict]", raw_result)


async def verify_zitadel_platform_alignment(
    *,
    config: ZitadelIdentityConfig,
    token_provider: AccessTokenProviderPort,
    http_client: httpx.AsyncClient,
    ready_timeout_seconds: float = 30.0,
) -> ZitadelAlignmentResult:
    """Verify .env machine key, platform org, admin user, and UCP project match live Zitadel."""
    missing_fields = [
        name
        for name, val in (
            ("IDENTITY_MACHINE_KEY", config.machine_key),
            ("IDENTITY_PLATFORM_ORG_ID", config.platform_org_id),
            ("IDENTITY_PLATFORM_ADMIN_ID", config.platform_admin_id),
            ("IDENTITY_UCP_PROJECT_ID", config.ucp_project_id),
        )
        if not val.strip()
    ]
    if missing_fields:
        return ZitadelAlignmentResult(
            aligned=False,
            reason=ZitadelDriftReason.MISSING_CREDENTIALS,
            detail=f"Missing required Zitadel identity variables: {', '.join(missing_fields)}",
        )

    is_ready = await wait_for_zitadel_ready(
        http_client,
        config.zitadel_url,
        timeout_seconds=ready_timeout_seconds,
    )
    if not is_ready:
        return ZitadelAlignmentResult(
            aligned=False,
            reason=ZitadelDriftReason.UNREACHABLE,
            detail=f"Zitadel did not become ready at {config.zitadel_url}",
        )

    try:
        access_token = await token_provider.get_access_token()
    except (ZitadelMachineAuthenticationError, ValueError) as exc:
        return ZitadelAlignmentResult(
            aligned=False,
            reason=ZitadelDriftReason.MACHINE_AUTH_FAILED,
            detail=str(exc),
        )

    base_url = config.zitadel_url.rstrip("/")
    try:
        all_orgs = await _list_all_orgs(http_client, base_url, access_token)
    except httpx.HTTPError as exc:
        return ZitadelAlignmentResult(
            aligned=False,
            reason=ZitadelDriftReason.MACHINE_AUTH_FAILED,
            detail=f"Failed to query Zitadel organizations: {exc}",
        )

    if not any(org.get("id") == config.platform_org_id for org in all_orgs):
        return ZitadelAlignmentResult(
            aligned=False,
            reason=ZitadelDriftReason.PLATFORM_ORG_MISSING,
            detail=(
                f"IDENTITY_PLATFORM_ORG_ID={config.platform_org_id} was not found in live Zitadel"
            ),
        )

    scoped_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "x-zitadel-orgid": config.platform_org_id,
    }

    try:
        admin_resp = await http_client.get(
            f"{base_url}/management/v1/users/{config.platform_admin_id}",
            headers=scoped_headers,
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        return ZitadelAlignmentResult(
            aligned=False,
            reason=ZitadelDriftReason.PLATFORM_ADMIN_MISSING,
            detail=f"Failed to verify IDENTITY_PLATFORM_ADMIN_ID in Zitadel: {exc}",
        )
    if admin_resp.status_code != 200:
        return ZitadelAlignmentResult(
            aligned=False,
            reason=ZitadelDriftReason.PLATFORM_ADMIN_MISSING,
            detail=(
                f"IDENTITY_PLATFORM_ADMIN_ID={config.platform_admin_id} returned HTTP "
                f"{admin_resp.status_code} in Zitadel"
            ),
        )

    try:
        proj_resp = await http_client.get(
            f"{base_url}/management/v1/projects/{config.ucp_project_id}",
            headers=scoped_headers,
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        return ZitadelAlignmentResult(
            aligned=False,
            reason=ZitadelDriftReason.UCP_PROJECT_MISSING,
            detail=f"Failed to verify IDENTITY_UCP_PROJECT_ID in Zitadel: {exc}",
        )
    if proj_resp.status_code != 200:
        return ZitadelAlignmentResult(
            aligned=False,
            reason=ZitadelDriftReason.UCP_PROJECT_MISSING,
            detail=(
                f"IDENTITY_UCP_PROJECT_ID={config.ucp_project_id} returned HTTP "
                f"{proj_resp.status_code} in Zitadel"
            ),
        )

    return ZitadelAlignmentResult(
        aligned=True,
        access_token=access_token,
        all_orgs=tuple(all_orgs),
    )


async def cleanup_non_platform_zitadel_orgs(
    *,
    http_client: httpx.AsyncClient,
    zitadel_url: str,
    access_token: str,
    platform_org_id: str,
    all_orgs: tuple[ZitadelOrgDict, ...],
) -> int:
    """Rename and delete all non-platform, non-system Zitadel organizations."""
    base_url = zitadel_url.rstrip("/")
    tenant_orgs = [
        org
        for org in all_orgs
        if org.get("id")
        and org.get("id") != platform_org_id
        and org.get("name") != IDENTITY_SYSTEM_ORG_NAME
    ]
    if not tenant_orgs:
        logger.info("zitadel_no_tenant_orgs_to_delete")
        return 0

    deleted = 0
    for org in tenant_orgs:
        org_id = org["id"]
        org_name = org.get("name", "unknown")
        rename_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "x-zitadel-orgid": org_id,
        }
        rename_resp = await http_client.put(
            f"{base_url}/management/v1/orgs/me",
            headers=rename_headers,
            json={"name": f"DELETED-{org_id}"},
            timeout=15.0,
        )
        if rename_resp.status_code >= 400:
            logger.info(
                "zitadel_org_rename_before_delete_skipped",
                org_id=org_id,
                org_name=org_name,
                status_code=rename_resp.status_code,
            )

        delete_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        del_resp = await http_client.delete(
            f"{base_url}/admin/v1/orgs/{org_id}",
            headers=delete_headers,
            timeout=15.0,
        )
        if del_resp.status_code == 404:
            continue
        if del_resp.status_code >= 400:
            logger.error(
                "zitadel_org_delete_failed",
                org_id=org_id,
                org_name=org_name,
                status_code=del_resp.status_code,
            )
            continue
        deleted += 1
        logger.info("zitadel_org_deleted", org_id=org_id, org_name=org_name)

    return deleted


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
            Tenant.idp_tenant_id == platform_org_id,
        )
        .values(idp_tenant_id=None)
    )

    stmt_tenant = (
        pg_insert(Tenant)
        .values(
            id=PLATFORM_TENANT_ID,
            name="Platform Organization",
            slug="platform",
            idp_tenant_id=platform_org_id,
            status=LifecycleStatus.ACTIVE.value,
            deleted_at=None,
            deleted_by=None,
        )
        .on_conflict_do_update(
            index_elements=[Tenant.id],
            set_={
                "name": "Platform Organization",
                "slug": "platform",
                "idp_tenant_id": platform_org_id,
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
) -> None:
    digest = hashlib.sha256(platform_admin_id.encode()).hexdigest()[:16]
    platform_user_id = f"{UcpIdPrefix.USER.value}_{digest}"
    user_role_id = f"{UcpIdPrefix.USER_ROLE.value}_{digest}"

    await session.execute(
        update(User)
        .where(
            func.lower(User.email).in_([DEFAULT_ADMIN_EMAIL, LEGACY_ADMIN_EMAIL]),
            or_(User.idp_user_id != platform_admin_id, User.idp_user_id.is_(None)),
        )
        .values(idp_user_id=platform_admin_id, deleted_at=None, deleted_by=None)
    )

    stmt_user = (
        pg_insert(User)
        .values(
            id=platform_user_id,
            idp_user_id=platform_admin_id,
            email=DEFAULT_ADMIN_EMAIL,
            name="Platform Admin",
            status=LifecycleStatus.ACTIVE.value,
            deleted_at=None,
            deleted_by=None,
        )
        .on_conflict_do_update(
            index_elements=[User.idp_user_id],
            set_={
                "email": DEFAULT_ADMIN_EMAIL,
                "name": "Platform Admin",
                "status": LifecycleStatus.ACTIVE.value,
                "deleted_at": None,
                "deleted_by": None,
            },
        )
        .returning(User.id)
    )
    actual_user_id = str((await session.execute(stmt_user)).scalar_one())

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
    )


async def _seed_shards(
    session: AsyncSession,
    edi_shard_dsn: str,
    extra_shards: tuple[ShardSeedSpec, ...],
) -> None:
    shards_to_seed: list[ShardSeedSpec] = []
    if edi_shard_dsn:
        shards_to_seed.append(
            ShardSeedSpec(
                shard_id=EDI_PRIMARY_SHARD_ID,
                name="EDI Primary Shard",
                dsn=edi_shard_dsn,
            )
        )
    shards_to_seed.extend(spec for spec in extra_shards if spec.dsn)

    for spec in shards_to_seed:
        await session.execute(
            pg_insert(DatabaseShard)
            .values(
                id=spec.shard_id,
                name=spec.name,
                dsn=spec.dsn,
                status=DatabaseShardStatus.ACTIVE.value,
            )
            .on_conflict_do_update(
                index_elements=[DatabaseShard.id],
                set_={
                    "name": spec.name,
                    "dsn": spec.dsn,
                    "status": DatabaseShardStatus.ACTIVE.value,
                },
            )
        )
        logger.info("primary_shard_seeded", shard_id=spec.shard_id)


async def _seed_edi_app(session: AsyncSession, edi_project_id: str) -> None:
    if edi_project_id:
        await session.execute(
            update(App).where(App.id == EDI_CORE_APP_ID).values(idp_project_id=edi_project_id)
        )
        logger.info("edi_app_project_seeded", idp_project_id=edi_project_id)


async def seed_platform_bootstrap(
    *,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    config: PlatformSeedConfig,
) -> None:
    """Idempotently seed sentinel tenant, canonical roles, platform admin, shards, and app links."""
    async with session_factory() as session:
        await _seed_platform_tenant(session, config.platform_org_id)
        platform_admin_role_id = await _seed_platform_roles(session)
        await _seed_platform_admin(
            session,
            config.platform_admin_id,
            platform_admin_role_id,
        )
        await _seed_shards(session, config.edi_shard_dsn, config.extra_shards)
        await _seed_edi_app(session, config.edi_project_id)
        await session.commit()
