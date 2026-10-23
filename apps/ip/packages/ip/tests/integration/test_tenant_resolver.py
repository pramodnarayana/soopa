"""Narrow integration tests for IpTenantResolver and IpTenantUoWProvider against PostgreSQL SAVEPOINTs."""

from __future__ import annotations

import pytest
from database.testing import TransactionalTestRouter
from ip.engine.adapters.outbound.database.data_plane.uow import (
    SqlAlchemyIpDataPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.tenant_resolver import (
    IP_APP_SLUG,
    IpTenantResolver,
)
from ip.engine.adapters.outbound.database.tenant_uow_provider import (
    IpTenantUoWProvider,
)
from ip.engine.domain.exceptions import IpErrorCode, TenantShardNotFoundError
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_ip_tenant_resolver_resolves_shard_and_returns_result(
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    resolver = IpTenantResolver(db_router=transactional_router)
    assert resolver.app_slug == IP_APP_SLUG == "ip"

    ok_res = await resolver.resolve_tenant_shard(seeded_ip_tenant)
    assert ok_res.is_ok is True
    assert ok_res.value is not None
    shard_id, shard_dsn = ok_res.value
    assert shard_id == "ip_shard_1"
    assert "ip_shard" in shard_dsn

    missing_res = await resolver.resolve_tenant_shard("ten_unknown")
    assert missing_res.is_err is True
    assert isinstance(missing_res.error, TenantShardNotFoundError)
    assert missing_res.error.code == IpErrorCode.TENANT_SHARD_NOT_FOUND
    assert missing_res.error.http_status == 404


@pytest.mark.asyncio
async def test_ip_tenant_uow_provider_yields_scoped_tenant_uow(
    transactional_router: TransactionalTestRouter,
    seeded_ip_tenant: str,
) -> None:
    resolver = IpTenantResolver(db_router=transactional_router)
    provider = IpTenantUoWProvider(resolver=resolver, db_router=transactional_router)

    shard_res = await provider.resolve_shard_info(seeded_ip_tenant)
    assert shard_res.is_ok is True
    assert shard_res.value is not None
    shard_id, shard_dsn = shard_res.value
    assert shard_id == "ip_shard_1"
    assert "ip_shard" in shard_dsn

    async with provider.get_data_plane_uow(seeded_ip_tenant, shard_id, shard_dsn) as uow:
        assert isinstance(uow, SqlAlchemyIpDataPlaneUnitOfWork)
        res = await uow.tenant_session.execute(
            text("SELECT current_setting('platform.current_tenant_id', true)")
        )
        assert res.scalar_one() == seeded_ip_tenant
