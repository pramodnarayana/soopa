"""Narrow SAVEPOINT integration tests for SqlAlchemyTenantRepository."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from database.models.identity import Tenant as TenantORM
from database.types import GlobalSession
from identity.domain.constants import IdentityIdPrefix
from ip.engine.adapters.outbound.database.control_plane.tenant_repository import (
    SessionScopedTenantRepository,
    SqlAlchemyTenantRepository,
)
from seedwork import generate_id
from sqlalchemy.ext.asyncio import AsyncSession
from ucp.domain.constants import LifecycleStatus

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_tenant_repository_excludes_soft_deleted_tenants(
    global_session: GlobalSession,
) -> None:
    repo = SqlAlchemyTenantRepository(global_session)

    active_id = generate_id(IdentityIdPrefix.TENANT.value)
    active_slug = f"acme-active-{active_id[-8:]}"
    active_idp = f"org_active_{active_id[-8:]}"
    global_session.add(
        TenantORM(
            id=active_id,
            name="Acme Active Tenant",
            slug=active_slug,
            status=LifecycleStatus.ACTIVE,
            idp_tenant_id=active_idp,
        )
    )

    deleted_id = generate_id(IdentityIdPrefix.TENANT.value)
    deleted_slug = f"acme-deleted-{deleted_id[-8:]}"
    deleted_idp = f"org_deleted_{deleted_id[-8:]}"
    global_session.add(
        TenantORM(
            id=deleted_id,
            name="Acme Soft Deleted Tenant",
            slug=deleted_slug,
            status=LifecycleStatus.INACTIVE,
            idp_tenant_id=deleted_idp,
            deleted_at=datetime.now(UTC),
        )
    )
    await global_session.flush()

    by_idp = await repo.get_by_idp_tenant_id(f"  {active_idp}  ")
    assert by_idp is not None
    assert by_idp.id == active_id
    assert by_idp.slug == active_slug
    assert by_idp.idp_tenant_id == active_idp

    by_slug = await repo.get_by_slug(f"  {active_slug.upper()}  ")
    assert by_slug is not None
    assert by_slug.id == active_id

    assert await repo.get_by_idp_tenant_id(deleted_idp) is None
    assert await repo.get_by_slug(deleted_slug) is None
    assert await repo.get_by_idp_tenant_id("   ") is None
    assert await repo.get_by_slug("   ") is None


@pytest.mark.asyncio
async def test_session_scoped_tenant_repository_closes_each_read_scope(
    global_session: GlobalSession,
) -> None:
    entered_count = 0
    exited_count = 0

    @contextlib.asynccontextmanager
    async def _session_scope() -> AsyncIterator[AsyncSession]:
        nonlocal entered_count, exited_count
        entered_count += 1
        try:
            yield global_session
        finally:
            exited_count += 1

    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    slug = f"scoped-tenant-{tenant_id[-8:]}"
    idp_id = f"org_scoped_{tenant_id[-8:]}"
    global_session.add(
        TenantORM(
            id=tenant_id,
            name="Scoped Tenant",
            slug=slug,
            status=LifecycleStatus.ACTIVE,
            idp_tenant_id=idp_id,
        )
    )
    await global_session.flush()

    scoped_repo = SessionScopedTenantRepository(
        session_scope=_session_scope,
        repository_factory=SqlAlchemyTenantRepository,
    )
    by_idp = await scoped_repo.get_by_idp_tenant_id(idp_id)
    assert by_idp is not None
    assert by_idp.id == tenant_id
    assert entered_count == 1
    assert exited_count == 1

    by_slug = await scoped_repo.get_by_slug(slug)
    assert by_slug is not None
    assert by_slug.id == tenant_id
    assert entered_count == 2
    assert exited_count == 2
