"""Alembic environment for Integration Platform Data Plane (tenant shards, public schema)."""

import asyncio

from alembic import context
from database.testing import get_test_shard_url_sync
from database.utils import normalize_to_asyncpg, shard_connect_args
import ip.application.domains.energy.models
import ip.application.domains.tms.models
import ip.engine.adapters.outbound.database.models.data_plane
from ip.engine.adapters.outbound.database.models.base import IpTenantBase
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# Structural registry anchoring both Engine Data Plane and Application Canonical Domain models into IpTenantBase
_REGISTERED_TENANT_ORM_MODULES = (
    ip.engine.adapters.outbound.database.models.data_plane,
    ip.application.domains.energy.models,
    ip.application.domains.tms.models,
)

config = context.config

target_metadata = IpTenantBase.registry.metadata

def _resolve_tenant_db_url() -> str:
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url
    global_url = str(load_settings_safely(PlatformDatabaseSettings).global_url)
    return get_test_shard_url_sync(global_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=_resolve_tenant_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    tenant_db_url = _resolve_tenant_db_url()
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
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
