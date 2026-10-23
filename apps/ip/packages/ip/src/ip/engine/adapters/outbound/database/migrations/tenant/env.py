"""Alembic environment for Integration Platform Data Plane (tenant shards, public schema)."""

from __future__ import annotations

import asyncio
import os

from alembic import context
from database.testing import get_test_shard_url_sync
from database.utils import normalize_to_asyncpg, shard_connect_args
from ip.engine.adapters.outbound.database.migrations.tenant.registry import (
    ENGINE_CORE,
)
from ip.engine.adapters.outbound.database.models.base import IpTenantBase
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config

if not config.get_main_option("version_locations"):
    config.set_main_option("version_locations", str(ENGINE_CORE.versions_dir))

target_metadata = IpTenantBase.registry.metadata


def _resolve_tenant_db_url() -> str:
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url
    env_url = os.environ.get("IP_DATABASE_URL") or os.environ.get("SHARD_OVERRIDES__IP_SHARD_1")
    if env_url:
        return env_url
    settings = load_settings_safely(PlatformDatabaseSettings)
    shard_override = settings.shard_overrides.get("ip_shard_1")
    if shard_override:
        return shard_override
    global_url = str(settings.global_url)
    return get_test_shard_url_sync(global_url)


def include_object(
    object: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object,
) -> bool:
    """Filter tables to only those defined on IpTenantBase metadata."""
    if type_ == "table" and name:
        return name in target_metadata.tables
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=_resolve_tenant_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations(tenant_db_url: str) -> None:
    normalized_url = normalize_to_asyncpg(tenant_db_url)

    connectable = create_async_engine(
        normalized_url or tenant_db_url,
        poolclass=pool.NullPool,
        connect_args=shard_connect_args(),
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    tenant_db_url = _resolve_tenant_db_url()
    asyncio.run(run_async_migrations(tenant_db_url))


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
