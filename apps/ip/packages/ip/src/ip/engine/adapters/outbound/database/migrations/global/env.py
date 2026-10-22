"""Alembic environment for Integration Platform Control Plane (global_db, schema 'ip')."""

import asyncio

from alembic import context
import ip.engine.adapters.outbound.database.models.control_plane
from ip.engine.adapters.outbound.database.models.base import IpGlobalBase
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.schema import SchemaItem, Table

# Structural registry anchoring all Control Plane ORM models into Alembic metadata
_REGISTERED_GLOBAL_ORM_MODULES = (
    ip.engine.adapters.outbound.database.models.control_plane,
)

config = context.config

target_metadata = IpGlobalBase.registry.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = load_settings_safely(PlatformDatabaseSettings).global_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="ip",
    )

    with context.begin_transaction():
        context.run_migrations()


def include_name(
    name: str | None,
    type_: str,
    parent_names: dict[str, str | None],
) -> bool:
    if type_ == "schema":
        return name == "ip"
    return True


def include_object(
    obj: SchemaItem,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: SchemaItem | None,
) -> bool:
    if type_ == "table" and isinstance(obj, Table):
        return obj.schema == "ip"
    return True


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        version_table_schema="ip",
    )

    with context.begin_transaction():
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS ip;"))
        has_version_table = connection.execute(
            text("SELECT to_regclass('ip.alembic_version') IS NOT NULL")
        ).scalar()
        current_rev = (
            connection.execute(text("SELECT version_num FROM ip.alembic_version")).scalar()
            if has_version_table
            else None
        )
        if current_rev != "0001_initial_global_schema":
            connection.execute(text("DROP SCHEMA ip CASCADE;"))
            connection.execute(text("CREATE SCHEMA ip;"))
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using an async engine."""
    settings = load_settings_safely(PlatformDatabaseSettings)
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.global_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
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
