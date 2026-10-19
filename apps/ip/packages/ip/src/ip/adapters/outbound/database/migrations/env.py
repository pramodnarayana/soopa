import asyncio
from logging.config import fileConfig  # noqa: TID251 - Required by Alembic setup

# Import models to ensure they are registered with IpBase.registry
import ip.adapters.outbound.database.models.catalog_model
import ip.adapters.outbound.database.models.connection_model
import ip.adapters.outbound.database.models.outbox_model  # noqa: F401
from alembic import context
from ip.adapters.outbound.database.models.base import IpBase
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = IpBase.registry.metadata


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


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == "ip"
    return True


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table":
        return getattr(object, "schema", None) == "ip"
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


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
