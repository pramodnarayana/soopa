"""Root test fixtures for Integration Platform (apps/ip/packages/ip/tests).

Enforces transactional isolation via nested PostgreSQL SAVEPOINTs (`join_transaction_mode="create_savepoint"`).
Every database-backed test runs inside an uncommitted outer transaction on `global_db` (localhost:5432)
and `ip_shard` (localhost:5434) that rolls back completely upon completion, guaranteeing zero shared-state
pollution across Control Plane (`IpGlobalBase`) and Data Plane (`IpTenantBase`).
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import cast

import ip.application.domains.energy.models as _ip_energy_models
import ip.application.domains.tms.models as _ip_tms_models
import ip.engine.adapters.outbound.database.models.control_plane as _ip_cp_models
import ip.engine.adapters.outbound.database.models.data_plane as _ip_dp_models
import pytest_asyncio
from database.constants import DatabaseShardStatus
from database.models.identity import Tenant as TenantORM
from database.provider import get_async_engine
from database.testing import TransactionalTestRouter
from database.types import GlobalSession, TenantSession
from dotenv import load_dotenv
from ip.engine.adapters.outbound.database.models.base import IpGlobalBase, IpTenantBase
from orchestration.adapters.outbound.database.models import WorkflowBase
from seedwork import generate_id
from seedwork.id_registry import DomainIdPrefix
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from ucp.domain.constants import LifecycleStatus
from ucp_models.sharding import DatabaseShard as UcpDatabaseShard
from ucp_models.sharding import ShardRegistry as UcpShardRegistry
from ucp_models.subscriptions import App as UcpApp
from ucp_models.subscriptions import AppSubscription as UcpAppSubscription

load_dotenv()

_REGISTERED_MODEL_MODULES = (
    _ip_energy_models,
    _ip_tms_models,
    _ip_cp_models,
    _ip_dp_models,
)


def _get_global_db_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://ucp_admin:ucp_password@localhost:5432/global_db",
    )


def _get_shard_db_url() -> str:
    return (
        os.environ.get("IP_DATABASE_URL")
        or os.environ.get("SHARD_OVERRIDES__IP_SHARD_1")
        or "postgresql+asyncpg://ip:ip_password@localhost:5434/ip_shard"
    )


@pytest_asyncio.fixture(scope="function")
async def global_db_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create an async SQLAlchemy engine pointing to the Control Plane test database."""
    engine = get_async_engine(_get_global_db_url())
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS ip;"))
        await conn.run_sync(IpGlobalBase.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def tenant_db_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create an async SQLAlchemy engine pointing to the Data Plane tenant shard test database (ip_shard)."""
    engine = get_async_engine(_get_shard_db_url())
    async with engine.begin() as conn:
        await conn.run_sync(IpTenantBase.metadata.create_all)
        await conn.run_sync(WorkflowBase.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def global_db_connection(
    global_db_engine: AsyncEngine,
) -> AsyncGenerator[AsyncConnection, None]:
    """Provide a Control Plane connection wrapped in an outer transaction that rolls back after each test."""
    connection = await global_db_engine.connect()
    transaction = await connection.begin()
    try:
        yield connection
    finally:
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture(scope="function")
async def tenant_db_connection(
    tenant_db_engine: AsyncEngine,
) -> AsyncGenerator[AsyncConnection, None]:
    """Provide a Data Plane connection wrapped in an outer transaction that rolls back after each test."""
    connection = await tenant_db_engine.connect()
    transaction = await connection.begin()
    try:
        yield connection
    finally:
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture(scope="function")
async def global_session(
    global_db_connection: AsyncConnection,
) -> AsyncGenerator[GlobalSession, None]:
    """Provide a SAVEPOINT-isolated Control Plane GlobalSession."""
    session_factory = async_sessionmaker(
        bind=global_db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )
    async with session_factory() as session:
        session.info["session_type"] = "global"
        yield cast(GlobalSession, session)


@pytest_asyncio.fixture(scope="function")
async def tenant_session(
    tenant_db_connection: AsyncConnection,
) -> AsyncGenerator[TenantSession, None]:
    """Provide a SAVEPOINT-isolated Data Plane TenantSession."""
    session_factory = async_sessionmaker(
        bind=tenant_db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )
    async with session_factory() as session:
        session.info["session_type"] = "tenant"
        yield cast(TenantSession, session)


@pytest_asyncio.fixture(scope="function")
async def transactional_router(
    global_db_connection: AsyncConnection,
    tenant_db_connection: AsyncConnection,
) -> TransactionalTestRouter:
    """Provide the platform TransactionalTestRouter bound to SAVEPOINT connections."""
    return TransactionalTestRouter(
        global_conn=global_db_connection,
        shard_conn=tenant_db_connection,
        global_url=_get_global_db_url(),
        shard_url=_get_shard_db_url(),
    )


@pytest_asyncio.fixture(scope="function")
async def seeded_ip_tenant(global_session: GlobalSession) -> str:
    """Self-contained fixture seeding an active Tenant, IP App, Subscription, and ShardRegistry inside the savepoint."""
    tenant_id = generate_id(DomainIdPrefix.TENANT.value)
    tenant = TenantORM(
        id=tenant_id,
        name="IP Narrow Integration Tenant",
        slug=f"ip-narrow-{tenant_id[-8:]}",
        status=LifecycleStatus.ACTIVE,
        idp_tenant_id=f"org_{tenant_id[-8:]}",
    )
    global_session.add(tenant)
    await global_session.flush()

    apps_res = await global_session.execute(text("SELECT id FROM ucp.apps WHERE slug = 'ip'"))
    ip_app_id = str(apps_res.scalar() or "app_ip_core")

    existing_app = await global_session.get(UcpApp, ip_app_id)
    if existing_app is None:
        global_session.add(
            UcpApp(
                id=ip_app_id,
                slug="ip",
                name="Integration Platform",
                description="Enterprise Integration Platform",
            )
        )
        await global_session.flush()

    global_session.add(
        UcpAppSubscription(
            tenant_id=tenant_id,
            app_id=ip_app_id,
            status=LifecycleStatus.ACTIVE,
            tier="enterprise",
        )
    )
    await global_session.flush()

    shard_id = "ip_shard_1"
    existing_shard = await global_session.get(UcpDatabaseShard, shard_id)
    if existing_shard is None:
        global_session.add(
            UcpDatabaseShard(
                id=shard_id,
                name="IP Primary Shard",
                dsn=_get_shard_db_url(),
                status=DatabaseShardStatus.ACTIVE,
            )
        )
    else:
        existing_shard.dsn = _get_shard_db_url()
    await global_session.flush()

    global_session.add(
        UcpShardRegistry(
            tenant_id=tenant_id,
            app_id=ip_app_id,
            shard_id=shard_id,
        )
    )
    await global_session.flush()
    return tenant_id
