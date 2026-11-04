"""Narrow PostgreSQL integration test verifying shell_lifespan executes the identity drift guard."""

from __future__ import annotations

import tempfile
from contextlib import AbstractAsyncContextManager

import pytest
import structlog.testing
from database.models.identity import Role as RoleORM
from database.models.identity import Tenant as TenantORM
from identity.domain.constants import IdentityIdPrefix
from identity.domain.identity_context import PLATFORM_TENANT_ID
from secret_store import AwsSecretsManagerAdapter
from seedwork import generate_id
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ucp.bootstrap.identity_bootstrap import (
    PlatformSeedConfig,
    purge_non_platform_tenants,
    seed_platform_bootstrap,
)
from ucp.domain.constants import LifecycleStatus

from unified_api.adapters.inbound.http.dependencies.edi.services import get_secret_store
from unified_api.bootstrap.identity_drift_guard import verify_platform_tenant_idp_alignment
from unified_api.bootstrap.lifespan import shell_lifespan
from unified_api.main import app as _app
from unified_api.main import edi_app

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_shell_lifespan_awaits_identity_drift_guard_on_startup(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        platform_tenant = await session.get(TenantORM, PLATFORM_TENANT_ID)
        if platform_tenant is None:
            platform_tenant = TenantORM(
                id=PLATFORM_TENANT_ID,
                name="Platform Admin Tenant",
                slug="platform-admin",
                status=LifecycleStatus.ACTIVE,
                idp_tenant_id="org_drifted_startup_probe",
            )
            session.add(platform_tenant)
        else:
            platform_tenant.idp_tenant_id = "org_drifted_startup_probe"
            platform_tenant.deleted_at = None
        await session.commit()

    with tempfile.TemporaryDirectory() as temp_secrets_dir:

        async def override_get_secret_store() -> AwsSecretsManagerAdapter:
            return AwsSecretsManagerAdapter(secrets_mount_path=temp_secrets_dir)

        prev_provider = _app.state.db_provider
        prev_router = _app.state.db_router
        _app.dependency_overrides[get_secret_store] = override_get_secret_store
        if edi_app is not None:
            edi_app.dependency_overrides[get_secret_store] = override_get_secret_store

        try:
            with structlog.testing.capture_logs() as captured:
                async with shell_lifespan(_app):
                    mismatch_logs = [
                        entry
                        for entry in captured
                        if entry.get("event") == "local_identity_org_id_mismatch"
                    ]
                    assert len(mismatch_logs) == 1
                    assert mismatch_logs[0]["db_org_id"] == "org_drifted_startup_probe"

            assert _app.state.db_provider.closed is True
        finally:
            _app.state.db_provider = prev_provider
            _app.state.db_router = prev_router
            _app.dependency_overrides.pop(get_secret_store, None)
            if edi_app is not None:
                edi_app.dependency_overrides.pop(get_secret_store, None)


@pytest.mark.asyncio
async def test_purge_non_platform_tenants_and_self_healing_platform_seed_preserve_login_alignment(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    extra_tenant_a = generate_id(IdentityIdPrefix.TENANT.value)
    extra_tenant_b = generate_id(IdentityIdPrefix.TENANT.value)
    colliding_org_id = "org_live_zitadel_999"

    async with db_session_factory() as session:
        session.add_all(
            [
                TenantORM(
                    id=extra_tenant_a,
                    name=f"Tenant A {extra_tenant_a[-6:]}",
                    slug=f"ten-a-{extra_tenant_a[-6:]}",
                    status=LifecycleStatus.ACTIVE,
                    idp_tenant_id=colliding_org_id,
                ),
                TenantORM(
                    id=extra_tenant_b,
                    name=f"Tenant B {extra_tenant_b[-6:]}",
                    slug=f"ten-b-{extra_tenant_b[-6:]}",
                    status=LifecycleStatus.ACTIVE,
                ),
            ]
        )
        await session.commit()

    purged = await purge_non_platform_tenants(
        session_factory=db_session_factory,
        batch_size=1,
        yield_seconds=0.0,
    )
    assert purged >= 2

    # Simulate damaged roles (as previously caused by TRUNCATE CASCADE) and verify seed self-heals
    async with db_session_factory() as session:
        await session.execute(
            delete(RoleORM).where(
                RoleORM.tenant_id == PLATFORM_TENANT_ID,
                RoleORM.name == "PlatformAdmin",
            )
        )
        await session.commit()

    await seed_platform_bootstrap(
        session_factory=db_session_factory,
        config=PlatformSeedConfig(
            platform_org_id=colliding_org_id,
            platform_admin_id="usr_live_zitadel_admin_999",
            edi_shard_dsn="postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_test",
            edi_project_id="proj_edi_live_999",
        ),
    )

    async with db_session_factory() as session:
        assert await session.get(TenantORM, extra_tenant_a) is None
        assert await session.get(TenantORM, extra_tenant_b) is None
        platform_tenant = await session.get(TenantORM, PLATFORM_TENANT_ID)
        assert platform_tenant is not None
        assert platform_tenant.idp_tenant_id == colliding_org_id
        assert platform_tenant.deleted_at is None

        admin_role = (
            await session.execute(
                select(RoleORM).where(
                    RoleORM.tenant_id == PLATFORM_TENANT_ID,
                    RoleORM.name == "PlatformAdmin",
                )
            )
        ).scalar_one_or_none()
        assert admin_role is not None
        assert "platform:admin" in admin_role.capabilities

    class _SessionFactoryProvider:
        def session(self) -> AbstractAsyncContextManager[AsyncSession]:
            return db_session_factory()

    aligned = await verify_platform_tenant_idp_alignment(
        db_provider=_SessionFactoryProvider(),
        expected_platform_org_id=colliding_org_id,
    )
    assert aligned is True
