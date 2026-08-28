import asyncio
from logging.config import fileConfig  # noqa: TID251 - Required by Alembic for setup

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from edi.adapters.outbound.database.models.data_plane import TenantBase

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = TenantBase.metadata

# For generating migrations, we connect to shard 1 as a representative database
from edi.config.settings import get_settings

_ini_url = config.get_main_option("sqlalchemy.url")
if _ini_url:
    TENANT_DB_URL = _ini_url
else:
    fallback = get_settings().database.default_shard_url
    if not fallback:
        raise ValueError("sqlalchemy.url is missing and SHARD_1_URL fallback is not set.")
    TENANT_DB_URL = fallback


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=TENANT_DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, include_schemas=True)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    # Ensure we are using the asyncpg driver
    configuration["sqlalchemy.url"] = TENANT_DB_URL.replace(
        "postgresql://", "postgresql+asyncpg://"
    )

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
